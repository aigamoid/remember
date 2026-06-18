"""FastAPI APIサーバ。Discord Bot（moimoichan_Discordbot）から呼ばれる。

起動方法:
    .venv/bin/uvicorn src.api:app --host 0.0.0.0 --port 8000
    docker compose up api
"""

from __future__ import annotations

import asyncio
import os
from typing import Callable, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()  # uvicorn 直接起動でも .env を読み込む

from src import db, quota
from src.config import load_config
from src.embedder import Embedder
from src.rag.engine import RagEngine
from src.rag.llm import ChatLLM
from src.rag.reranker import Reranker
from src.usage import UsageRecorder
from src.vectorstore import VectorStore


def _parse_user_id(user: Optional[str]) -> Optional[str]:
    """ログ用 user 文字列（"channel_id:user_id" 形式）から user_id を取り出す。"""
    if not user:
        return None
    return user.rsplit(":", 1)[-1] or None


def _next_plan(conn, current_key: str) -> Optional[dict]:
    """アップグレード案内用に、現プランより上位（質問上限が多い）の最安プランを返す。"""
    defs = db.fetch_plan_defs(conn)
    cur = next((d for d in defs if d["plan_key"] == current_key), None)
    if cur is None:
        return None
    higher = [
        d for d in defs
        if d["daily_question_limit"] > cur["daily_question_limit"]
    ]
    return higher[0] if higher else None


def default_quota_checker(guild_id: str) -> Optional[str]:
    """サーバーの本日の質問数が日次上限以上なら案内文を返す（OK なら None）。

    DB障害時は fail-open（None＝通す）。回答自体を止めないため。
    """
    try:
        conn = db.get_connection(init=False)
    except Exception as e:
        print(f"[WARN] quota確認スキップ（DB接続失敗・fail-open）: {e}")
        return None
    try:
        plan = db.get_guild_plan(conn, guild_id)
        since = quota.jst_day_start_utc_iso()
        used = db.count_questions_since(conn, guild_id, since)
        if quota.question_quota_exceeded(used, plan["daily_question_limit"]):
            return quota.daily_limit_message(
                plan["daily_question_limit"], _next_plan(conn, plan["plan_key"])
            )
        return None
    except Exception as e:
        print(f"[WARN] quota確認失敗（fail-open）: {e}")
        return None
    finally:
        conn.close()


class ChatRequest(BaseModel):
    guild_id: str
    query: str
    user: Optional[str] = None  # ログ用（"channel_id:user_id" 形式を想定）
    guild_name: Optional[str] = None  # プロンプト用サーバー名（未指定なら config の値）
    # 直近の会話履歴（マルチターン・OI-10）。{"role": "user"|"assistant",
    # "content": str} の古い順リスト。呼び出し側（Bot/CLI）が保持して渡す。
    history: Optional[list[dict]] = None


class ChatResponse(BaseModel):
    answer: str
    rewritten_query: str
    sources: list


def build_engine(cfg: dict) -> RagEngine:
    """config.yml から RagEngine を組み立てる。"""
    qdrant_cfg = cfg.get("qdrant", {})
    emb_cfg = cfg.get("embedding", {})
    openai_cfg = cfg.get("openai", {})

    # QDRANT_URL はコンテナ内からの接続用オーバーライド（compose では http://qdrant:6333）
    store = VectorStore(
        url=os.environ.get("QDRANT_URL")
        or qdrant_cfg.get("url", "http://localhost:6333"),
        collection=qdrant_cfg.get("collection", "waiwai_chunks"),
        vector_size=emb_cfg.get("dimensions", 1536),
    )
    embedder = Embedder(
        model=emb_cfg.get("model", "text-embedding-3-small"),
        dimensions=emb_cfg.get("dimensions", 1536),
    )
    llm = ChatLLM(
        api_key=openai_cfg.get("api_key") or os.environ.get("OPENROUTER_API_KEY"),
        base_url=openai_cfg.get("base_url", "https://openrouter.ai/api/v1"),
    )
    # リランカー（OI-9）: 設定で有効な場合のみ生成。APIキーは JINA_API_KEY。
    rerank_cfg = cfg.get("rag", {}).get("reranker", {})
    reranker = None
    if rerank_cfg.get("enabled", False):
        reranker = Reranker(
            api_key=os.environ.get("JINA_API_KEY"),
            model=rerank_cfg.get("model", "jina-reranker-v2-base-multilingual"),
        )
    return RagEngine(
        cfg, store, embedder, llm,
        usage_recorder=UsageRecorder(), reranker=reranker,
    )


def create_app(
    engine: Optional[RagEngine] = None,
    quota_checker: Optional[Callable[[str], Optional[str]]] = None,
) -> FastAPI:
    """アプリを生成する。engine / quota_checker を渡すとテスト用に差し替えられる。

    quota_checker(guild_id) -> 案内文 or None。本番では startup で DB 版を設定。
    engine 注入時（テスト）は quota_checker 未指定なら quota チェックを行わない。
    """
    app = FastAPI(title="remember API")
    app.state.engine = engine
    app.state.quota_checker = quota_checker

    @app.on_event("startup")
    async def _startup() -> None:
        if app.state.engine is not None:
            return  # テスト等で engine を注入済みなら DB 初期化はしない
        app.state.engine = build_engine(load_config())
        if app.state.quota_checker is None:
            app.state.quota_checker = default_quota_checker
        # 各テーブルを用意（DB未起動でも /chat は動くので失敗は無視）
        try:
            conn = db.get_connection(init=True)
            conn.close()
        except Exception as e:
            print(f"[WARN] スキーマ初期化スキップ: {e}")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        if not req.query.strip():
            raise HTTPException(status_code=422, detail="query が空です")
        # プラン上限チェック（超過なら回答せず案内＝コスト発生なし・OI-14 C-2）
        checker = app.state.quota_checker
        if checker is not None:
            message = await asyncio.to_thread(checker, req.guild_id)
            if message:
                return ChatResponse(answer=message, rewritten_query="", sources=[])
        result = await app.state.engine.answer(
            req.guild_id, req.query, guild_name=req.guild_name,
            user_id=_parse_user_id(req.user), history=req.history,
        )
        return ChatResponse(**result)

    return app


app = create_app()
