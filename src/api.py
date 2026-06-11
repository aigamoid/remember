"""FastAPI APIサーバ。Discord Bot（moimoichan_Discordbot）から呼ばれる。

起動方法:
    .venv/bin/uvicorn src.api:app --host 0.0.0.0 --port 8000
    docker compose up api
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.config import load_config
from src.embedder import Embedder
from src.rag.engine import RagEngine
from src.rag.llm import ChatLLM
from src.vectorstore import VectorStore


class ChatRequest(BaseModel):
    guild_id: str
    query: str
    user: Optional[str] = None  # ログ用（"channel_id:user_id" 形式を想定）


class ChatResponse(BaseModel):
    answer: str
    rewritten_query: str
    sources: list


def build_engine(cfg: dict) -> RagEngine:
    """config.yml から RagEngine を組み立てる。"""
    qdrant_cfg = cfg.get("qdrant", {})
    emb_cfg = cfg.get("embedding", {})
    openai_cfg = cfg.get("openai", {})

    store = VectorStore(
        url=qdrant_cfg.get("url", "http://localhost:6333"),
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
    return RagEngine(cfg, store, embedder, llm)


def create_app(engine: Optional[RagEngine] = None) -> FastAPI:
    """アプリを生成する。engine を渡すとテスト用に差し替えられる。"""
    app = FastAPI(title="waiwai-oracle API")
    app.state.engine = engine

    @app.on_event("startup")
    async def _startup() -> None:
        if app.state.engine is None:
            app.state.engine = build_engine(load_config())

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        if not req.query.strip():
            raise HTTPException(status_code=422, detail="query が空です")
        result = await app.state.engine.answer(req.guild_id, req.query)
        return ChatResponse(**result)

    return app


app = create_app()
