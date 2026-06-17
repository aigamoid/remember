"""RAG回答エンジン: クエリ書き換え → ベクトル検索 → 回答生成。src/api.py から使用。

Difyフロー（Start → Query Rewriter → 知識検索 → LLM → 回答）の移植。
各 LLM/embedding 呼び出しの token 使用量を usage_recorder（src/usage.py）経由で
usage_log に記録する（コスト計測用・OI-14 C）。記録失敗は回答を止めない。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable

from src.embedder import Embedder
from src.rag.llm import ChatLLM, Usage
from src.rag.prompts import (
    ANSWER_SYSTEM_PROMPT,
    REWRITER_SYSTEM_PROMPT,
    build_context,
)
from src.usage import compute_cost
from src.vectorstore import VectorStore


class RagEngine:
    def __init__(
        self,
        cfg: dict,
        store: VectorStore,
        embedder: Embedder,
        llm: ChatLLM,
        usage_recorder: Callable[[list[dict]], None] | None = None,
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
        # 回答出力の上限（OI-16: completionの暴走を防ぐ安全弁）。
        self.answer_max_tokens: int = rag_cfg.get("answer_max_tokens", 1500)
        # マルチターン会話で渡す直近やり取りの上限（user+assistant のペア数・OI-10）。
        self.history_max_turns: int = rag_cfg.get("history_max_turns", 5)
        # 履歴の合計文字数バジェット（回答LLM向け）。長い回答が積み重なって
        # token が膨張するのを防ぐ。超えたら古いメッセージから落とす（0で無制限）。
        self.history_max_chars: int = rag_cfg.get("history_max_chars", 4000)
        # Query Rewriter に渡す履歴はさらに絞る（指示語解決には直近少数で十分。
        # rewriter にも履歴を積むと token が二重に増えるため）。
        self.rewriter_history_max_turns: int = rag_cfg.get(
            "rewriter_history_max_turns", 2
        )
        self.rewriter_history_max_chars: int = rag_cfg.get(
            "rewriter_history_max_chars", 1000
        )
        self.guild_name: str = rag_cfg.get("guild_name", "わいわい")
        self.tz_offset: int = cfg.get("chunk", {}).get("timezone_offset", 9)
        self.pricing: dict = cfg.get("pricing", {})
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.usage_recorder = usage_recorder

    def _now_str(self) -> str:
        tz = timezone(timedelta(hours=self.tz_offset))
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M JST")

    def _prep_history(
        self, history: list[dict] | None, max_turns: int, max_chars: int
    ) -> list[dict]:
        """呼び出し側から渡された会話履歴を検証して LLM に渡せる形に整える。

        role が user/assistant で content が非空の要素だけ残し、(1) 直近
        max_turns ペア（= max_turns*2 メッセージ）に丸めたうえで、(2) 合計
        content が max_chars 文字以内に収まるよう古いメッセージから落とす
        （max_chars<=0 で文字数制限なし）。長い回答の積み重ねによる token 膨張を
        防ぐ（OI-10）。戻り値は古い順の [{"role", "content"}, ...]。
        """
        if not history or max_turns <= 0:
            return []
        cleaned = [
            {"role": h["role"], "content": str(h["content"])}
            for h in history
            if isinstance(h, dict)
            and h.get("role") in ("user", "assistant")
            and str(h.get("content") or "").strip()
        ]
        cleaned = cleaned[-(max_turns * 2):]
        if max_chars and max_chars > 0:
            # 新しい方から積み、バジェットを超えたら打ち切る（最低1件は残す）。
            kept: list[dict] = []
            total = 0
            for m in reversed(cleaned):
                c = len(m["content"])
                if kept and total + c > max_chars:
                    break
                kept.append(m)
                total += c
            cleaned = list(reversed(kept))
        return cleaned

    def _record(
        self,
        events: list[dict] | None,
        kind: str,
        model: str,
        usage: Usage,
    ) -> None:
        """LLM 呼び出し1回分の usage イベントを events に追加する（コストも算出）。"""
        if events is None:
            return
        events.append({
            "kind": kind,
            "model": model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "cost_usd": compute_cost(
                self.pricing, model, usage.prompt_tokens, usage.completion_tokens
            ),
        })

    async def _flush(
        self, events: list[dict], guild_id: str, user_id: str | None
    ) -> None:
        """蓄積した usage イベントを recorder に渡して記録する。失敗しても無視。"""
        if not self.usage_recorder or not events:
            return
        rows = [
            {**ev, "guild_id": str(guild_id), "user_id": user_id} for ev in events
        ]
        try:
            await asyncio.to_thread(self.usage_recorder, rows)
        except Exception as e:  # 計測の失敗で回答を落とさない
            print(f"[WARN] usage flush 失敗: {e}")

    async def rewrite(
        self,
        query: str,
        events: list[dict] | None = None,
        history: list[dict] | None = None,
    ) -> str:
        """検索用クエリに書き換える。失敗・空応答時は元のクエリを返す。

        history（直近の会話）を渡すと「それ」「さっきの件」などの指示語を
        会話文脈から具体化できる（REWRITER_SYSTEM_PROMPT のルール2・OI-10）。
        """
        system = REWRITER_SYSTEM_PROMPT.replace(
            "{current_datetime}", self._now_str()
        )
        try:
            comp = await self.llm.complete(
                self.rewriter_model, system, query,
                temperature=0.2, max_tokens=self.rewriter_max_tokens,
                history=history,
            )
        except Exception as e:
            print(f"[WARN] Query Rewriter 失敗（元クエリで検索続行）: {e}")
            return query
        self._record(events, "rewrite", comp.model, comp.usage)
        return comp.text.strip() or query

    async def answer(
        self,
        guild_id: str,
        query: str,
        guild_name: str | None = None,
        user_id: str | None = None,
        history: list[dict] | None = None,
    ) -> dict:
        """質問に回答する。戻り値: {answer, rewritten_query, sources}

        guild_name はプロンプトに埋め込むサーバー名。
        未指定なら config の rag.guild_name を使う（単一サーバー時代の互換）。
        user_id は usage_log の集計用（任意）。
        history は直近の会話（{"role","content"} の古い順リスト）。渡すと
        クエリ書き換えと回答の両方が会話文脈を踏まえる（マルチターン・OI-10）。
        """
        events: list[dict] = []
        # 回答LLM向け（広め）と Query Rewriter 向け（狭め）で別々に整える。
        # rewriter のペア数は回答側を超えないようにする。
        hist_ans = self._prep_history(
            history, self.history_max_turns, self.history_max_chars
        )
        hist_rw = self._prep_history(
            history,
            min(self.rewriter_history_max_turns, self.history_max_turns),
            self.rewriter_history_max_chars,
        )
        rewritten = await self.rewrite(query, events, history=hist_rw)

        vector, emb_tokens = await asyncio.to_thread(
            self.embedder.embed_one_with_usage, rewritten
        )
        emb_model = getattr(self.embedder, "model", "text-embedding-3-small")
        self._record(events, "embedding", emb_model, Usage(emb_tokens, 0, emb_tokens))

        hits = await asyncio.to_thread(
            self.store.search, str(guild_id), vector, self.top_k
        )

        system = ANSWER_SYSTEM_PROMPT.replace(
            "{guild_name}", guild_name or self.guild_name
        ).replace("{current_datetime}", self._now_str()).replace(
            "{context}", build_context(hits)
        )
        comp = await self.llm.complete(
            self.answer_model, system, query,
            temperature=0.7, max_tokens=self.answer_max_tokens,
            history=hist_ans,
        )
        self._record(events, "answer", comp.model, comp.usage)

        await self._flush(events, guild_id, user_id)

        sources = [
            {
                "channel_name": h.get("channel_name"),
                "anchor_timestamp": h.get("anchor_timestamp"),
                "score": h.get("score"),
            }
            for h in hits
        ]
        return {
            "answer": comp.text,
            "rewritten_query": rewritten,
            "sources": sources,
        }
