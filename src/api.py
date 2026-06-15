"""FastAPI APIサーバ。Discord Bot（moimoichan_Discordbot）から呼ばれる。

起動方法:
    .venv/bin/uvicorn src.api:app --host 0.0.0.0 --port 8000
    docker compose up api
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()  # uvicorn 直接起動でも .env を読み込む

from src import db
from src.config import load_config
from src.embedder import Embedder
from src.rag.engine import RagEngine
from src.rag.llm import ChatLLM
from src.usage import UsageRecorder
from src.vectorstore import VectorStore


def _parse_user_id(user: Optional[str]) -> Optional[str]:
    """ログ用 user 文字列（"channel_id:user_id" 形式）から user_id を取り出す。"""
    if not user:
        return None
    return user.rsplit(":", 1)[-1] or None


class ChatRequest(BaseModel):
    guild_id: str
    query: str
    user: Optional[str] = None  # ログ用（"channel_id:user_id" 形式を想定）
    guild_name: Optional[str] = None  # プロンプト用サーバー名（未指定なら config の値）


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
    return RagEngine(cfg, store, embedder, llm, usage_recorder=UsageRecorder())


def create_app(engine: Optional[RagEngine] = None) -> FastAPI:
    """アプリを生成する。engine を渡すとテスト用に差し替えられる。"""
    app = FastAPI(title="waiwai-oracle API")
    app.state.engine = engine

    @app.on_event("startup")
    async def _startup() -> None:
        if app.state.engine is not None:
            return  # テスト等で engine を注入済みなら DB 初期化はしない
        app.state.engine = build_engine(load_config())
        # usage_log などのテーブルを用意（DB未起動でも /chat は動くので失敗は無視）
        try:
            conn = db.get_connection(init=True)
            conn.close()
        except Exception as e:
            print(f"[WARN] usage_log スキーマ初期化スキップ: {e}")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        if not req.query.strip():
            raise HTTPException(status_code=422, detail="query が空です")
        result = await app.state.engine.answer(
            req.guild_id, req.query, guild_name=req.guild_name,
            user_id=_parse_user_id(req.user),
        )
        return ChatResponse(**result)

    return app


app = create_app()
