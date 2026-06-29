"""RAG回答エンジン: クエリ書き換え → ベクトル検索 → 回答生成。src/api.py から使用。

Difyフロー（Start → Query Rewriter → 知識検索 → LLM → 回答）の移植。
各 LLM/embedding 呼び出しの token 使用量を usage_recorder（src/usage.py）経由で
usage_log に記録する（コスト計測用・OI-14 C）。記録失敗は回答を止めない。
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from src.embedder import Embedder
from src.rag.llm import ChatLLM, Usage
from src.rag.prompts import (
    ANSWER_SYSTEM_PROMPT,
    MEMORY_EXTRACT_PROMPT,
    MEMORY_RECONCILE_PROMPT,
    MEMORY_SECTION,
    _contains_sensitive,
    NO_SEARCH_SENTINEL,
    PERSONA_EXTRACT_PROMPT,
    REWRITER_SYSTEM_PROMPT,
    SKIP_CONTEXT,
    SPEAKER_SECTION,
    build_context,
    build_memories,
    build_mimic_section,
    persona_is_empty,
    sanitize_persona_card,
)
from src.rag.reranker import Reranker
from src.sparse import SparseEncoder
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
        reranker: Reranker | None = None,
        trace_recorder: Callable[[dict], None] | None = None,
        memory_provider: Callable[[str], list[dict]] | None = None,
        mimic_provider: Callable[[str, str], dict | None] | None = None,
        sparse_encoder: SparseEncoder | None = None,
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
        # リランカー（OI-9）。enabled かつ reranker が渡された時のみ有効。
        # dense で rerank_top_n 件取り、cross-encoder で top_k 件に精選する。
        rerank_cfg = rag_cfg.get("reranker", {})
        self.rerank_enabled: bool = bool(rerank_cfg.get("enabled", False))
        self.rerank_top_n: int = rerank_cfg.get("top_n", 30)
        # 検索ゲート（OI-23）。Query Rewriter が [NO_SEARCH] を返したら埋め込み・
        # 検索・リランクをスキップし、素の雑談として回答する（コスト/レイテンシ削減）。
        # 誤スキップは記憶RAGの価値を損なうため、判定は「迷ったら検索」に倒している。
        self.search_gate: bool = bool(rag_cfg.get("search_gate", True))
        # デバッグトレース（OI-21）。enabled かつ trace_recorder が渡された時のみ記録。
        # 質問・ヒットチャンク・回答を残すためプライバシー上の既定はオフ。
        self.trace_enabled: bool = bool(rag_cfg.get("debug_trace", False))
        # 明示メモリ（OI-24）。enabled かつ memory_provider が渡された時のみ、
        # guild の「教わった事実」を回答プロンプトに全件注入する（既定オフ）。
        self.memory_enabled: bool = bool(rag_cfg.get("memory_enabled", False))
        # 真似っこモード（#49）。enabled かつ mimic_provider が渡された時のみ、
        # その channel で真似中の対象の人格カードを {mimic_section} に注入する（既定オフ）。
        self.mimic_enabled: bool = bool(rag_cfg.get("mimic_enabled", False))
        # 人格カード生成は answer_model を流用する（profile_model は新設しない・設計 §0）。
        mimic_cfg = rag_cfg.get("mimic", {})
        self.mimic_sample_limit: int = mimic_cfg.get("sample_limit", 300)
        self.mimic_min_sample: int = mimic_cfg.get("min_sample_count", 30)
        # 自動記憶（#56 案C）。enabled の時だけ worker が会話から事実を抽出し pending 候補を積む。
        # 既定オフ＝従来どおり明示メモリのみ。誤抽出は重大なので全件 admin 承認を経て初めて有効化する。
        auto_mem_cfg = rag_cfg.get("auto_memory", {})
        self.auto_memory_enabled: bool = bool(auto_mem_cfg.get("enabled", False))
        self.auto_memory_max_chunks: int = auto_mem_cfg.get("max_chunks", 30)
        # 突合は複数操作を JSON 配列で返すため rewriter_max_tokens(256) では途中で切れる。
        # 専用に広めの上限を取る（既定800・出力が切れると配列が壊れて 0 件になる）。
        self.auto_memory_max_tokens: int = auto_mem_cfg.get("max_tokens", 800)
        # ハイブリッド検索（#54）。enabled かつ sparse_encoder が渡された時のみ、dense と
        # BM25 sparse を RRF 融合する（既定オフ＝dense-only で現行どおり）。本番ONは実データA/B後。
        hybrid_cfg = rag_cfg.get("hybrid", {})
        self.hybrid_enabled: bool = bool(hybrid_cfg.get("enabled", False))
        self.hybrid_prefetch_k: int = hybrid_cfg.get("prefetch_k", 30)
        self.tz_offset: int = cfg.get("chunk", {}).get("timezone_offset", 9)
        self.pricing: dict = cfg.get("pricing", {})
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.usage_recorder = usage_recorder
        self.reranker = reranker
        self.trace_recorder = trace_recorder
        self.memory_provider = memory_provider
        self.mimic_provider = mimic_provider
        self.sparse_encoder = sparse_encoder

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

    async def _flush_trace(self, row: dict) -> None:
        """1リクエスト分のトレースを recorder に渡して記録する。失敗しても無視。"""
        if not (self.trace_enabled and self.trace_recorder):
            return
        try:
            await asyncio.to_thread(self.trace_recorder, row)
        except Exception as e:  # トレースの失敗で回答を落とさない
            print(f"[WARN] trace flush 失敗: {e}")

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

    @staticmethod
    def _parse_memory_json(text: str) -> dict | None:
        """抽出LLMの出力からJSONオブジェクトを取り出す。崩れていれば None。"""
        t = text.strip()
        if t.startswith("```"):
            t = t.strip("`")
            t = t[t.find("{"):]
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j < 0:
            return None
        try:
            return json.loads(t[i:j + 1])
        except Exception:
            return None

    async def extract_memory(
        self,
        guild_id: str,
        text: str,
        speaker_name: str | None = None,
        user_id: str | None = None,
    ) -> dict | None:
        """「覚えておいて」発話から保存すべき事実を抽出する（OI-24・書き込み）。

        戻り値: {"subject": str|None, "content": str}、または覚えるべき事実が無ければ None。
        rewriter_model（安価）で抽出し usage を記録する。LLM失敗・JSON崩れ・content空は
        None（保存しない＝誤爆の二重ガード）。speaker_name があれば本人参照を解決する。
        """
        speaker_line = (
            f"話者（いまの発話者）の名前: {speaker_name}\n"
            if speaker_name and speaker_name.strip() else ""
        )
        system = MEMORY_EXTRACT_PROMPT.replace("{speaker_line}", speaker_line)
        events: list[dict] = []
        try:
            comp = await self.llm.complete(
                self.rewriter_model, system, text,
                temperature=0.1, max_tokens=self.rewriter_max_tokens,
            )
        except Exception as e:
            print(f"[WARN] メモリ抽出失敗（保存しない）: {e}")
            return None
        self._record(events, "memory_extract", comp.model, comp.usage)
        await self._flush(events, guild_id, user_id)
        data = self._parse_memory_json(comp.text)
        if not data:
            return None
        content = str(data.get("content") or "").strip()
        if not content or content.lower() == "null":
            return None
        subject = str(data.get("subject") or "").strip() or None
        if subject and subject.lower() == "null":
            subject = None
        return {"subject": subject, "content": content}

    @staticmethod
    def _parse_memory_ops(text: str) -> list[dict]:
        """突合LLMの出力からJSON配列を取り出す。崩れていれば []（#56）。"""
        t = text.strip()
        if t.startswith("```"):
            t = t.strip("`")
        i, j = t.find("["), t.rfind("]")
        if i < 0 or j < 0:
            return []
        try:
            data = json.loads(t[i:j + 1])
        except Exception:
            return []
        return [op for op in data if isinstance(op, dict)] if isinstance(data, list) else []

    async def reconcile_memories(
        self,
        guild_id: str,
        conversation_text: str,
        existing: list[dict],
        guild_name: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        """会話から永続事実を抽出し、既存メモリと突合して操作の配列を返す（#56 案C・書き込みはしない）。

        戻り値: 検証済みの操作 [{"op","subject","content","target_id","reason"}, ...]。
        op は add/update/delete のみ（noop と不正は除外）。update/delete は target_id が existing に
        存在する時のみ採用する（誤爆の二重ガード）。LLM失敗・JSON崩れ・該当なしは []。
        rewriter_model（安価）で実行し usage を記録する。**ここでは保存しない**（呼び出し側が pending 投入）。
        """
        if not conversation_text.strip():
            return []
        valid_ids = {m["id"] for m in existing}
        if existing:
            existing_text = "\n".join(
                f"[{m['id']}] "
                + (f"{m['subject']}: " if m.get("subject") else "")
                + str(m.get("content") or "")
                for m in existing
            )
        else:
            existing_text = "（まだ何も覚えていない）"
        system = (
            MEMORY_RECONCILE_PROMPT
            .replace("{guild_name}", guild_name or self.guild_name)
            .replace("{existing}", existing_text)
            .replace("{conversation}", conversation_text)
        )
        events: list[dict] = []
        try:
            comp = await self.llm.complete(
                self.rewriter_model, system,
                "上記の会話から記憶操作をJSON配列で出力して。",
                temperature=0.1, max_tokens=self.auto_memory_max_tokens,
            )
        except Exception as e:
            print(f"[WARN] 記憶突合失敗（候補を作らない）: {e}")
            return []
        self._record(events, "memory_reconcile", comp.model, comp.usage)
        await self._flush(events, guild_id, user_id)

        ops: list[dict] = []
        for raw in self._parse_memory_ops(comp.text):
            op = str(raw.get("op") or "").strip().lower()
            if op not in ("add", "update", "delete"):
                continue  # noop・不明は捨てる
            content = str(raw.get("content") or "").strip()
            if content.lower() == "null":
                content = ""
            if op in ("add", "update") and not content:
                continue  # 本文が無い add/update は無効
            target_id = raw.get("target_id")
            try:
                target_id = int(target_id) if target_id is not None else None
            except (TypeError, ValueError):
                target_id = None
            if op in ("update", "delete") and target_id not in valid_ids:
                continue  # 対象が既存に無い update/delete は捨てる（ID幻覚ガード）
            subject = str(raw.get("subject") or "").strip() or None
            if subject and subject.lower() == "null":
                subject = None
            # センシティブ属性の二重ガード（#56）: プロンプト指示だけに頼らず、保存前にも
            # denylist で弾く（persona の sanitize_persona_card と同じ思想）。違反は破棄。
            if _contains_sensitive(content) or (subject and _contains_sensitive(subject)):
                continue
            ops.append({
                "op": op,
                "subject": subject,
                "content": content or None,
                "target_id": target_id,
                "reason": str(raw.get("reason") or "").strip() or None,
            })
        return ops

    async def build_persona_card(
        self,
        guild_id: str,
        display_name: str,
        samples: list[dict],
        user_id: str | None = None,
    ) -> dict | None:
        """対象者の発言サンプルから人格カードを生成する（#49・書き込み）。

        戻り値: 正規化済みカード dict（personality/speech_style/likes/nicknames/
        catchphrases/confidence）、または素材不足・LLM失敗・JSON崩れ・センシティブ除去後に
        実質空なら None（=真似を開始しない・二重ガード）。answer_model を流用し usage を記録。
        samples は新しい順の [{"content","timestamp","channel_name"}, ...]（db.fetch_member_messages）。
        """
        lines = [
            str(s.get("content") or "").strip()
            for s in samples
            if str(s.get("content") or "").strip()
        ]
        if not lines:
            return None
        # プロンプト肥大を避け、サンプルは行頭に「- 」を付けて連結（古い→新しいの順に戻す）。
        sample_text = "\n".join(f"- {ln}" for ln in reversed(lines))
        system = PERSONA_EXTRACT_PROMPT.replace(
            "{display_name}", display_name
        ).replace("{samples}", sample_text)
        events: list[dict] = []
        try:
            comp = await self.llm.complete(
                self.answer_model, system, "上記の発言から人格プロファイルをJSONで出力して。",
                temperature=0.2, max_tokens=self.answer_max_tokens,
            )
        except Exception as e:
            print(f"[WARN] 人格カード生成失敗（真似を開始しない）: {e}")
            return None
        self._record(events, "mimic_profile", comp.model, comp.usage)
        await self._flush(events, guild_id, user_id)
        data = self._parse_memory_json(comp.text)
        if not data:
            return None
        card = sanitize_persona_card(data)
        if persona_is_empty(card):
            return None
        return card

    @staticmethod
    def _doc_for_rerank(hit: dict) -> str:
        """リランカーに渡すドキュメント文字列。context があれば前置きする。"""
        ctx = hit.get("context_text")
        chunk = hit.get("chunk_text", "")
        return f"{ctx}\n{chunk}" if ctx else chunk

    async def _rerank(
        self, query: str, hits: list[dict], events: list[dict] | None
    ) -> list[dict]:
        """hits を query との関連度で並べ替え、上位 top_k 件を返す。
        失敗時は dense 順のまま top_k 件にして返す（回答は止めない）。"""
        docs = [self._doc_for_rerank(h) for h in hits]
        try:
            result = await self.reranker.rerank(query, docs, self.top_k)
        except Exception as e:
            print(f"[WARN] リランク失敗（dense順で続行）: {e}")
            return hits[: self.top_k]
        self._record(
            events, "rerank", self.reranker.model,
            Usage(result.total_tokens, 0, result.total_tokens),
        )
        reranked = [hits[i] for i in result.order if 0 <= i < len(hits)]
        return reranked or hits[: self.top_k]

    async def answer(
        self,
        guild_id: str,
        query: str,
        guild_name: str | None = None,
        user_id: str | None = None,
        history: list[dict] | None = None,
        speaker_name: str | None = None,
        channel_id: str | None = None,
    ) -> dict:
        """質問に回答する。戻り値: {answer, rewritten_query, sources}

        guild_name はプロンプトに埋め込むサーバー名。
        未指定なら config の rag.guild_name を使う（単一サーバー時代の互換）。
        user_id は usage_log の集計用（任意）。
        history は直近の会話（{"role","content"} の古い順リスト）。渡すと
        クエリ書き換えと回答の両方が会話文脈を踏まえる（マルチターン・OI-10）。
        speaker_name は「いま話しかけている人」の表示名（任意・OI-22）。渡すと
        回答プロンプトに差し込み、本人を指す言葉や呼びかけを解釈できる。
        未指定（CLI等）のときは該当ブロックごと消える。
        """
        t0 = time.perf_counter()
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

        # 検索ゲート（OI-23）。Rewriter が [NO_SEARCH] を返したら、雑談・一般質問と
        # みなして埋め込み・検索・リランクを丸ごとスキップする（コスト/レイテンシ削減）。
        search_skipped = self.search_gate and NO_SEARCH_SENTINEL in rewritten
        use_rerank = (
            not search_skipped and self.reranker is not None and self.rerank_enabled
        )
        if search_skipped:
            hits: list[dict] = []
            context = SKIP_CONTEXT
        else:
            vector, emb_tokens = await asyncio.to_thread(
                self.embedder.embed_one_with_usage, rewritten
            )
            emb_model = getattr(self.embedder, "model", "text-embedding-3-small")
            self._record(
                events, "embedding", emb_model, Usage(emb_tokens, 0, emb_tokens)
            )

            # ハイブリッド検索（#54）。有効かつ encoder があれば、クエリの BM25 sparse を
            # ローカル生成して dense と RRF 融合する（sparse はAPIコスト0）。
            use_hybrid = self.hybrid_enabled and self.sparse_encoder is not None
            sparse = self.sparse_encoder.encode(rewritten) if use_hybrid else None

            # リランク有効時は多め（rerank_top_n）に取って後で top_k に精選する。
            candidate_k = (
                max(self.rerank_top_n, self.top_k) if use_rerank else self.top_k
            )
            hits = await asyncio.to_thread(
                self.store.search,
                str(guild_id),
                vector,
                candidate_k,
                sparse,
                self.hybrid_prefetch_k,
            )
            if use_rerank and hits:
                hits = await self._rerank(rewritten, hits, events)
            context = build_context(hits)

        # 発言者名（OI-22）。あればブロックを差し込み、無ければ空文字で消す。
        speaker_section = (
            SPEAKER_SECTION.replace("{speaker}", speaker_name)
            if speaker_name and speaker_name.strip()
            else ""
        )
        # 明示メモリ（OI-24）。有効時のみ guild の「教わった事実」を全件取得して注入する。
        # 取得失敗・0件・無効ならブロックごと消す（回答は止めない）。
        memory_section = ""
        if self.memory_enabled and self.memory_provider:
            try:
                mem_rows = await asyncio.to_thread(
                    self.memory_provider, str(guild_id)
                )
            except Exception as e:
                print(f"[WARN] メモリ取得失敗（メモリ無しで続行）: {e}")
                mem_rows = []
            memories_text = build_memories(mem_rows or [])
            if memories_text:
                memory_section = MEMORY_SECTION.replace("{memories}", memories_text)

        # 真似っこモード（#49）。有効時のみ、その channel で真似中の対象の人格カードを
        # 取得して {mimic_section} に注入する。真似中でない・取得失敗・実質空ならブロックごと
        # 消す（回答は止めない）。scope=channel 固定なので channel_id 必須。
        mimic_section = ""
        if self.mimic_enabled and self.mimic_provider and channel_id:
            try:
                mimic = await asyncio.to_thread(
                    self.mimic_provider, str(guild_id), str(channel_id)
                )
            except Exception as e:
                print(f"[WARN] mimic 取得失敗（真似なしで続行）: {e}")
                mimic = None
            if mimic:
                mimic_section = build_mimic_section(
                    mimic.get("card") or {}, mimic.get("display_name") or ""
                )

        system = ANSWER_SYSTEM_PROMPT.replace(
            "{guild_name}", guild_name or self.guild_name
        ).replace("{current_datetime}", self._now_str()).replace(
            "{speaker_section}", speaker_section
        ).replace(
            "{mimic_section}", mimic_section
        ).replace(
            "{taught_memories}", memory_section
        ).replace(
            "{context}", context
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

        # デバッグトレース（OI-21）。有効時のみ、質問・ヒットチャンク本文・回答を
        # まとめて chat_trace に残す（記録失敗は回答を止めない）。
        if self.trace_enabled and self.trace_recorder:
            await self._flush_trace({
                "guild_id": str(guild_id),
                "user_id": user_id,
                "question": query,
                "rewritten_query": rewritten,
                "answer": comp.text,
                "sources": [
                    {
                        "channel_name": h.get("channel_name"),
                        "anchor_timestamp": h.get("anchor_timestamp"),
                        "score": h.get("score"),
                        "chunk_text": h.get("chunk_text"),
                        "context_text": h.get("context_text"),
                    }
                    for h in hits
                ],
                "answer_model": comp.model,
                "rerank_enabled": bool(use_rerank),
                "hybrid_enabled": bool(self.hybrid_enabled and self.sparse_encoder),
                "prompt_tokens": comp.usage.prompt_tokens,
                "completion_tokens": comp.usage.completion_tokens,
                "total_tokens": sum(e.get("total_tokens", 0) for e in events),
                "cost_usd": sum(e.get("cost_usd", 0.0) for e in events),
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            })

        return {
            "answer": comp.text,
            "rewritten_query": rewritten,
            "sources": sources,
            "search_skipped": search_skipped,
        }
