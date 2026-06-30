"""FastAPI APIサーバ。Discord Bot（moimoichan_Discordbot）から呼ばれる。

起動方法:
    .venv/bin/uvicorn src.api:app --host 0.0.0.0 --port 8000
    docker compose up api
"""

from __future__ import annotations

import asyncio
import hmac
import os
from typing import Callable, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv()  # uvicorn 直接起動でも .env を読み込む

from src import billing, db, quota
from src.config import load_config
from src.embedder import Embedder
from src.memory import MemoryProvider
from src.mimic import MimicProvider, MimicStore
from src.rag.engine import RagEngine
from src.rag.prompts import build_mimic_declaration
from src.sparse import SparseEncoder
from src.rag.llm import ChatLLM
from src.rag.reranker import Reranker
from src.trace import TraceRecorder
from src.usage import UsageRecorder
from src.vectorstore import VectorStore

_ENV_API_TOKEN = object()


def _parse_user_id(user: Optional[str]) -> Optional[str]:
    """ログ用 user 文字列（"channel_id:user_id" 形式）から user_id を取り出す。"""
    if not user:
        return None
    return user.rsplit(":", 1)[-1] or None


def _parse_channel_id(user: Optional[str]) -> Optional[str]:
    """旧 user 文字列（"channel_id:user_id"）から channel_id を取り出す（#49・移行用）。

    ChatRequest.channel_id が正典（設計 §0）。未指定時の後方互換として user から復元する。
    ":" を含まない場合は channel 情報なしとみなす（None）。
    """
    if not user or ":" not in user:
        return None
    return user.rsplit(":", 1)[0] or None


def _verify_api_token(configured_token: Optional[str], supplied_token: Optional[str]) -> None:
    """Bot→API の共有シークレットを検証する。

    ORACLE_API_TOKEN 未設定時は後方互換のため fail-open（ローカル開発・既存テスト用）。
    設定済みなら X-Oracle-Token が無い/一致しないリクエストを 401 にする。
    """
    if not configured_token:
        return
    if not supplied_token or not hmac.compare_digest(supplied_token, configured_token):
        raise HTTPException(status_code=401, detail="invalid oracle api token")


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


def default_memory_saver(
    guild_id: str,
    content: str,
    subject: Optional[str] = None,
    created_by: Optional[str] = None,
    source_channel_id: Optional[str] = None,
) -> bool:
    """教わった事実を memories に保存する（OI-24・書き込み）。成功で True。

    接続・保存に失敗しても例外を投げず False を返す（呼び出し側は saved=false にする）。
    """
    try:
        conn = db.get_connection(init=False)
    except Exception as e:
        print(f"[WARN] メモリ保存スキップ（接続失敗）: {e}")
        return False
    try:
        db.insert_memory(
            conn, guild_id, content, subject=subject,
            created_by=created_by, source_channel_id=source_channel_id,
        )
        return True
    except Exception as e:
        print(f"[WARN] メモリ保存失敗: {e}")
        return False
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
    # いま話しかけている人の表示名（OI-22）。回答プロンプトに差し込む（任意）。
    speaker: Optional[str] = None
    # 発言があったチャンネルID（#49）。真似っこモードの状態解決に使う正典。
    # 未指定なら後方互換で user（"channel_id:user_id"）から復元する。
    channel_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    rewritten_query: str
    sources: list


class RememberRequest(BaseModel):
    guild_id: str
    text: str  # 「覚えておいて」を含むユーザー発話そのもの
    speaker: Optional[str] = None  # 話者の表示名（本人参照の解決用・OI-24）
    user: Optional[str] = None  # ログ用（"channel_id:user_id" 形式）
    channel_id: Optional[str] = None  # 教わったチャンネル（任意）


class RememberResponse(BaseModel):
    saved: bool
    subject: Optional[str] = None
    content: Optional[str] = None


class MimicStartRequest(BaseModel):
    guild_id: str
    target_id: str            # 真似する対象メンバーの Discord ユーザーID
    channel_id: str           # 真似を効かせる channel（scope=channel 固定）
    target_name: Optional[str] = None  # 表示名（未指定なら過去ログから解決）
    user: Optional[str] = None         # 実行者（ログ用・"channel_id:user_id"）


class MimicStartResponse(BaseModel):
    started: bool
    declaration: Optional[str] = None  # 開始時の宣言文（成功時）
    reason: Optional[str] = None       # 失敗理由（optout/素材不足/無効 等）
    sample_count: int = 0


class CheckoutRequest(BaseModel):
    guild_id: str
    plan_key: str


class PortalRequest(BaseModel):
    guild_id: str


class BillingUrlResponse(BaseModel):
    url: str


class MimicStopRequest(BaseModel):
    guild_id: str
    channel_id: str


class MimicStopResponse(BaseModel):
    stopped: bool


class MimicOptoutRequest(BaseModel):
    guild_id: str
    target_id: str            # opt-out する対象（通常は本人）
    user: Optional[str] = None


class MimicOptoutResponse(BaseModel):
    ok: bool


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
    # デバッグトレース（OI-21）: rag.debug_trace=true のときだけ recorder を渡す。
    # engine 側も同フラグを見るので二重ガード（既定OFF・プライバシー）。
    trace_recorder = None
    if cfg.get("rag", {}).get("debug_trace", False):
        trace_recorder = TraceRecorder()
    # 明示メモリ（OI-24）: rag.memory_enabled=true のときだけ provider を渡す。
    # engine 側も同フラグを見るので二重ガード（既定OFF）。
    memory_provider = None
    if cfg.get("rag", {}).get("memory_enabled", False):
        memory_provider = MemoryProvider()
    # 真似っこ（#49）: rag.mimic_enabled=true のときだけ provider を渡す（二重ガード・既定OFF）。
    mimic_provider = None
    if cfg.get("rag", {}).get("mimic_enabled", False):
        mimic_provider = MimicProvider()
    # ハイブリッド検索（#54）: rag.hybrid.enabled=true のときだけ encoder を渡す。
    # engine 側も同フラグを見るので二重ガード（既定OFF＝dense-only）。
    sparse_encoder = None
    if cfg.get("rag", {}).get("hybrid", {}).get("enabled", False):
        sparse_encoder = SparseEncoder()
    return RagEngine(
        cfg, store, embedder, llm,
        usage_recorder=UsageRecorder(), reranker=reranker,
        trace_recorder=trace_recorder, memory_provider=memory_provider,
        mimic_provider=mimic_provider,
        sparse_encoder=sparse_encoder,
    )


def create_app(
    engine: Optional[RagEngine] = None,
    quota_checker: Optional[Callable[[str], Optional[str]]] = None,
    memory_saver: Optional[Callable[..., bool]] = None,
    mimic_store: Optional[object] = None,
    api_token: Optional[str] | object = _ENV_API_TOKEN,
) -> FastAPI:
    """アプリを生成する。engine / quota_checker / memory_saver を渡すとテスト用に差し替えられる。

    quota_checker(guild_id) -> 案内文 or None。本番では startup で DB 版を設定。
    memory_saver(guild_id, content, subject, created_by, source_channel_id) -> bool。
    api_token は Bot→API の共有シークレット。未指定なら ORACLE_API_TOKEN 環境変数から読む。
    engine 注入時（テスト）は quota_checker / memory_saver 未指定ならそのチェック/保存を行わない。
    """
    app = FastAPI(title="remember API")
    app.state.engine = engine
    app.state.quota_checker = quota_checker
    app.state.memory_saver = memory_saver
    app.state.mimic_store = mimic_store
    app.state.api_token = (
        os.getenv("ORACLE_API_TOKEN") if api_token is _ENV_API_TOKEN else api_token
    )

    @app.on_event("startup")
    async def _startup() -> None:
        if app.state.engine is not None:
            return  # テスト等で engine を注入済みなら DB 初期化はしない
        app.state.engine = build_engine(load_config())
        if app.state.quota_checker is None:
            app.state.quota_checker = default_quota_checker
        if app.state.memory_saver is None:
            app.state.memory_saver = default_memory_saver
        if app.state.mimic_store is None:
            app.state.mimic_store = MimicStore()
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
    async def chat(
        req: ChatRequest,
        x_oracle_token: Optional[str] = Header(default=None),
    ) -> ChatResponse:
        _verify_api_token(app.state.api_token, x_oracle_token)
        if not req.query.strip():
            raise HTTPException(status_code=422, detail="query が空です")
        # プラン上限チェック（超過なら回答せず案内＝コスト発生なし・OI-14 C-2）
        checker = app.state.quota_checker
        if checker is not None:
            message = await asyncio.to_thread(checker, req.guild_id)
            if message:
                return ChatResponse(answer=message, rewritten_query="", sources=[])
        # channel_id は新フィールドが正典。未指定なら旧 user 埋め込みから復元（#49・移行）。
        channel_id = req.channel_id or _parse_channel_id(req.user)
        result = await app.state.engine.answer(
            req.guild_id, req.query, guild_name=req.guild_name,
            user_id=_parse_user_id(req.user), history=req.history,
            speaker_name=req.speaker, channel_id=channel_id,
        )
        return ChatResponse(**result)

    @app.post("/remember", response_model=RememberResponse)
    async def remember(
        req: RememberRequest,
        x_oracle_token: Optional[str] = Header(default=None),
    ) -> RememberResponse:
        """「覚えておいて」発話から事実を抽出して memories に保存する（OI-24・書き込み）。

        rag.memory_enabled が OFF、覚えるべき事実が無い、保存失敗のいずれも saved=false を返す
        （回答系と同じく「機能の失敗で例外を投げない」流儀）。
        """
        _verify_api_token(app.state.api_token, x_oracle_token)
        if not req.text.strip():
            raise HTTPException(status_code=422, detail="text が空です")
        engine = app.state.engine
        if not getattr(engine, "memory_enabled", False):
            return RememberResponse(saved=False)
        user_id = _parse_user_id(req.user)
        extracted = await engine.extract_memory(
            req.guild_id, req.text, speaker_name=req.speaker, user_id=user_id
        )
        if not extracted:
            return RememberResponse(saved=False)
        saver = app.state.memory_saver
        if saver is None:
            return RememberResponse(saved=False)
        ok = await asyncio.to_thread(
            saver, req.guild_id, extracted["content"], extracted["subject"],
            user_id, req.channel_id,
        )
        if not ok:
            return RememberResponse(saved=False)
        return RememberResponse(
            saved=True, subject=extracted["subject"], content=extracted["content"]
        )

    @app.post("/mimic/start", response_model=MimicStartResponse)
    async def mimic_start(
        req: MimicStartRequest,
        x_oracle_token: Optional[str] = Header(default=None),
    ) -> MimicStartResponse:
        """対象者をプロファイリングして真似を開始する（#49）。

        mimic 無効・opt-out・素材不足のいずれも started=false（カード生成もしない＝コスト最小）。
        """
        _verify_api_token(app.state.api_token, x_oracle_token)
        engine = app.state.engine
        store = app.state.mimic_store
        if not getattr(engine, "mimic_enabled", False) or store is None:
            return MimicStartResponse(started=False, reason="真似っこ機能はいま無効だよ〜")
        # opt-out 本人は真似しない（強制点・設計 §2）。
        consent = await asyncio.to_thread(
            store.get_consent, req.guild_id, req.target_id
        )
        if consent == "optout":
            return MimicStartResponse(
                started=False,
                reason="この人は『真似しないで』設定にしてるみたい。やめておくね",
            )
        samples = await asyncio.to_thread(
            store.fetch_samples, req.guild_id, req.target_id,
            getattr(engine, "mimic_sample_limit", 300),
        )
        if not samples:
            return MimicStartResponse(
                started=False,
                reason="その人の発言がまだ見つからないかも。取り込み済みか確認してね",
            )
        display_name = (
            req.target_name
            or await asyncio.to_thread(
                store.resolve_name, req.guild_id, req.target_id
            )
            or "その人"
        )
        user_id = _parse_user_id(req.user)
        card = await engine.build_persona_card(
            req.guild_id, display_name, samples, user_id=user_id
        )
        if not card:
            return MimicStartResponse(
                started=False, sample_count=len(samples),
                reason="うまく特徴がつかめなかった…発言が少ないか、似せられそうにないみたい",
            )
        await asyncio.to_thread(
            store.save_card, req.guild_id, req.target_id, display_name,
            card, len(samples), user_id,
        )
        await asyncio.to_thread(
            store.set_state, req.guild_id, req.channel_id, req.target_id, user_id
        )
        return MimicStartResponse(
            started=True,
            declaration=build_mimic_declaration(card, display_name),
            sample_count=len(samples),
        )

    @app.post("/billing/checkout", response_model=BillingUrlResponse)
    async def billing_checkout(
        req: CheckoutRequest,
        x_oracle_token: Optional[str] = Header(default=None),
    ) -> BillingUrlResponse:
        """サブスク申込の Stripe Checkout URL を返す（/oracle upgrade から）。"""
        _verify_api_token(app.state.api_token, x_oracle_token)
        if not billing.enabled():
            raise HTTPException(status_code=503, detail="billing is not configured")

        def run() -> str:
            conn = db.get_connection(init=False)
            try:
                return billing.create_checkout_session(
                    conn, req.guild_id, req.plan_key,
                    success_url=os.environ.get(
                        "BILLING_SUCCESS_URL", "https://stripe.com"),
                    cancel_url=os.environ.get(
                        "BILLING_CANCEL_URL", "https://stripe.com"),
                )
            finally:
                conn.close()

        try:
            url = await asyncio.to_thread(run)
        except billing.AlreadySubscribedError:
            raise HTTPException(status_code=409, detail="already_subscribed")
        except billing.UnknownPlanError:
            raise HTTPException(status_code=400, detail="invalid_plan")
        except billing.BillingError:
            raise HTTPException(status_code=502, detail="stripe_error")
        return BillingUrlResponse(url=url)

    @app.post("/billing/portal", response_model=BillingUrlResponse)
    async def billing_portal(
        req: PortalRequest,
        x_oracle_token: Optional[str] = Header(default=None),
    ) -> BillingUrlResponse:
        """解約・カード変更用の Customer Portal URL を返す（/oracle billing から）。"""
        _verify_api_token(app.state.api_token, x_oracle_token)
        if not billing.enabled():
            raise HTTPException(status_code=503, detail="billing is not configured")

        def run() -> Optional[str]:
            conn = db.get_connection(init=False)
            try:
                info = db.get_guild_billing(conn, req.guild_id)
                customer_id = info.get("stripe_customer_id") if info else None
                if not customer_id:
                    return None
                return billing.create_portal_session(
                    customer_id,
                    return_url=os.environ.get(
                        "BILLING_RETURN_URL", "https://stripe.com"),
                )
            finally:
                conn.close()

        try:
            url = await asyncio.to_thread(run)
        except billing.BillingError:
            raise HTTPException(status_code=502, detail="stripe_error")
        if url is None:
            raise HTTPException(status_code=404, detail="no_subscription")
        return BillingUrlResponse(url=url)

    @app.post("/billing/webhook")
    async def billing_webhook(request: Request) -> JSONResponse:
        """Stripe Webhook。署名検証して guild_plans を自動更新する。

        ACK 方針（Stripe の再送制御）:
          署名不正=400 / 一時障害(DB・Stripe取得・guild未着地)=5xx(再送) / 正常・設定ミス=200。
        ※ここは Stripe からの呼び出しなので ORACLE_API_TOKEN は要求しない（署名で認証）。
        """
        if not billing.enabled():
            raise HTTPException(status_code=503, detail="billing is not configured")
        payload = await request.body()
        sig = request.headers.get("Stripe-Signature", "")

        def run() -> dict:
            conn = db.get_connection(init=False)
            try:
                return billing.handle_event(conn, payload, sig)
            finally:
                conn.close()

        try:
            result = await asyncio.to_thread(run)
        except billing.WebhookSignatureError:
            raise HTTPException(status_code=400, detail="invalid_signature")
        except billing.WebhookRetryableError:
            # 5xx を返すと Stripe が自動で再送してくれる。
            raise HTTPException(status_code=503, detail="retry_later")
        except Exception as e:  # DB 障害など想定外も再送に倒す（握り潰さない）
            print(f"[WARN] webhook 処理失敗（再送させる）: {e}")
            raise HTTPException(status_code=500, detail="webhook_error")
        return JSONResponse({"received": True, **result})

    @app.post("/mimic/stop", response_model=MimicStopResponse)
    async def mimic_stop(
        req: MimicStopRequest,
        x_oracle_token: Optional[str] = Header(default=None),
    ) -> MimicStopResponse:
        """その channel の真似を解除する（#49）。"""
        _verify_api_token(app.state.api_token, x_oracle_token)
        store = app.state.mimic_store
        if store is None:
            return MimicStopResponse(stopped=False)
        stopped = await asyncio.to_thread(
            store.clear_state, req.guild_id, req.channel_id
        )
        return MimicStopResponse(stopped=bool(stopped))

    @app.post("/mimic/optout", response_model=MimicOptoutResponse)
    async def mimic_optout(
        req: MimicOptoutRequest,
        x_oracle_token: Optional[str] = Header(default=None),
    ) -> MimicOptoutResponse:
        """本人を真似対象から除外する（opt-out・#49・本人/管理者が実行）。"""
        _verify_api_token(app.state.api_token, x_oracle_token)
        store = app.state.mimic_store
        if store is None:
            return MimicOptoutResponse(ok=False)
        try:
            await asyncio.to_thread(
                store.set_consent, req.guild_id, req.target_id, "optout"
            )
        except Exception as e:
            print(f"[WARN] opt-out 失敗: {e}")
            return MimicOptoutResponse(ok=False)
        return MimicOptoutResponse(ok=True)

    return app


app = create_app()
