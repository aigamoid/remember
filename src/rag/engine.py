"""RAG回答エンジン: クエリ書き換え → ベクトル検索 → 回答生成。src/api.py から使用。

Difyフロー（Start → Query Rewriter → 知識検索 → LLM → 回答）の移植。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from src.embedder import Embedder
from src.rag.llm import ChatLLM
from src.rag.prompts import (
    ANSWER_SYSTEM_PROMPT,
    REWRITER_SYSTEM_PROMPT,
    build_context,
)
from src.vectorstore import VectorStore


class RagEngine:
    def __init__(
        self,
        cfg: dict,
        store: VectorStore,
        embedder: Embedder,
        llm: ChatLLM,
    ) -> None:
        rag_cfg = cfg.get("rag", {})
        self.rewriter_model: str = rag_cfg.get(
            "rewriter_model", "google/gemini-2.5-flash"
        )
        self.answer_model: str = rag_cfg.get(
            "answer_model", "moonshotai/kimi-k2-0905"
        )
        self.top_k: int = rag_cfg.get("top_k", 10)
        # 書き換え結果は短いので出力上限を絞る。未指定だとモデル既定の
        # 巨大な max_tokens を要求し、OpenRouterの残高確保で弾かれることがある。
        self.rewriter_max_tokens: int = rag_cfg.get("rewriter_max_tokens", 256)
        self.guild_name: str = rag_cfg.get("guild_name", "わいわい")
        self.tz_offset: int = cfg.get("chunk", {}).get("timezone_offset", 9)
        self.store = store
        self.embedder = embedder
        self.llm = llm

    def _now_str(self) -> str:
        tz = timezone(timedelta(hours=self.tz_offset))
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M JST")

    async def rewrite(self, query: str) -> str:
        """検索用クエリに書き換える。失敗・空応答時は元のクエリを返す。"""
        system = REWRITER_SYSTEM_PROMPT.replace(
            "{current_datetime}", self._now_str()
        )
        try:
            out = await self.llm.complete(
                self.rewriter_model, system, query,
                temperature=0.2, max_tokens=self.rewriter_max_tokens,
            )
        except Exception as e:
            print(f"[WARN] Query Rewriter 失敗（元クエリで検索続行）: {e}")
            return query
        return out.strip() or query

    async def answer(
        self, guild_id: str, query: str, guild_name: str | None = None
    ) -> dict:
        """質問に回答する。戻り値: {answer, rewritten_query, sources}

        guild_name はプロンプトに埋め込むサーバー名。
        未指定なら config の rag.guild_name を使う（単一サーバー時代の互換）。
        """
        rewritten = await self.rewrite(query)

        vector = await asyncio.to_thread(self.embedder.embed_one, rewritten)
        hits = await asyncio.to_thread(
            self.store.search, str(guild_id), vector, self.top_k
        )

        system = ANSWER_SYSTEM_PROMPT.replace(
            "{guild_name}", guild_name or self.guild_name
        ).replace("{context}", build_context(hits))
        answer_text = await self.llm.complete(
            self.answer_model, system, query, temperature=0.7
        )

        sources = [
            {
                "channel_name": h.get("channel_name"),
                "anchor_timestamp": h.get("anchor_timestamp"),
                "score": h.get("score"),
            }
            for h in hits
        ]
        return {
            "answer": answer_text,
            "rewritten_query": rewritten,
            "sources": sources,
        }
