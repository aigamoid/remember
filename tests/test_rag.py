"""src/rag/ のテスト（フェイクLLM・フェイクembedder・インメモリQdrant）"""

from __future__ import annotations

import asyncio

import pytest
from qdrant_client import QdrantClient

from src.rag.engine import RagEngine
from src.rag.llm import ChatLLM, Completion, Usage, strip_think
from src.rag.prompts import build_context
from src.vectorstore import VectorStore


class FakeLLM:
    """API を呼ばず固定応答を返す。呼び出し内容を記録する。

    responses の各要素は str（usage 0）か Completion か Exception。
    """

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def complete(
        self, model, system, user, temperature=0.7, max_tokens=None, history=None
    ):
        self.calls.append(
            {
                "model": model, "system": system, "user": user,
                "temperature": temperature, "max_tokens": max_tokens,
                "history": history,
            }
        )
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if isinstance(resp, Completion):
            return resp
        return Completion(text=resp, model=model)


class FakeEmbedder:
    model = "text-embedding-3-small"

    def __init__(self, dimensions: int = 4, tokens: int = 7) -> None:
        self.dimensions = dimensions
        self.tokens = tokens
        self.embedded: list[str] = []

    def embed(self, texts):
        self.embedded.extend(texts)
        return [[1.0] + [0.0] * (self.dimensions - 1) for _ in texts]

    def embed_one(self, text):
        return self.embed([text])[0]

    def embed_one_with_usage(self, text):
        return self.embed_one(text), self.tokens


@pytest.fixture
def store():
    s = VectorStore(
        client=QdrantClient(":memory:"), collection="test", vector_size=4
    )
    s.ensure_collection()
    return s


def _seed(store, guild_id="g1", chunk_text="昨日の飲み会の話", context_text=None):
    store.upsert(
        [{
            "guild_id": guild_id,
            "chunk_id": "c1",
            "channel_id": "ch1",
            "channel_name": "general",
            "chunk_text": chunk_text,
            "context_text": context_text,
            "anchor_timestamp": "2024-01-01T00:00:00+00:00",
        }],
        [[1.0, 0.0, 0.0, 0.0]],
    )


CFG = {"guild_id": "g1", "rag": {"top_k": 5}}


def _engine(store, llm) -> RagEngine:
    return RagEngine(CFG, store, FakeEmbedder(), llm)


# ── strip_think ─────────────────────────────────────────────────────────────

class TestStripThink:
    def test_removes_think_tag(self):
        assert strip_think("<think>考え中</think>答え") == "答え"

    def test_no_tag_unchanged(self):
        assert strip_think("そのまま") == "そのまま"


# ── ChatLLM.complete のメッセージ組み立て ───────────────────────────────────

class _RecordingClient:
    """OpenAI互換クライアントの最小フェイク。create に渡された messages を記録する。"""

    def __init__(self) -> None:
        self.captured: dict = {}
        outer = self

        class _Completions:
            async def create(self, *, model, messages, temperature, max_tokens):
                outer.captured = {"model": model, "messages": messages}

                class _Msg:
                    content = "応答本文"

                class _Choice:
                    message = _Msg()

                class _Resp:
                    choices = [_Choice()]
                    usage = None

                return _Resp()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class TestChatLLMMessages:
    def test_without_history_system_then_user(self):
        client = _RecordingClient()
        llm = ChatLLM(client=client)
        asyncio.run(llm.complete("m", "システム", "ユーザー"))
        roles = [m["role"] for m in client.captured["messages"]]
        assert roles == ["system", "user"]

    def test_history_inserted_between_system_and_user(self):
        client = _RecordingClient()
        llm = ChatLLM(client=client)
        hist = [
            {"role": "user", "content": "前q"},
            {"role": "assistant", "content": "前a"},
        ]
        asyncio.run(llm.complete("m", "システム", "今のq", history=hist))
        msgs = client.captured["messages"]
        assert [m["role"] for m in msgs] == [
            "system", "user", "assistant", "user"
        ]
        assert msgs[1]["content"] == "前q"
        assert msgs[-1]["content"] == "今のq"


# ── build_context ───────────────────────────────────────────────────────────

class TestBuildContext:
    def test_empty_hits(self):
        assert "見つからなかった" in build_context([])

    def test_chunk_only(self):
        out = build_context([{"chunk_text": "本文A", "context_text": None}])
        assert out == "本文A"

    def test_with_context_text(self):
        out = build_context([{"chunk_text": "本文A", "context_text": "文脈A"}])
        assert "[CONTEXT]\n文脈A\n[CHUNK]\n本文A" == out

    def test_multiple_hits_separated(self):
        out = build_context(
            [
                {"chunk_text": "本文A", "context_text": None},
                {"chunk_text": "本文B", "context_text": None},
            ]
        )
        assert "\n\n---\n\n" in out


# ── RagEngine.rewrite ───────────────────────────────────────────────────────

class TestRewrite:
    def test_returns_llm_output(self, store):
        llm = FakeLLM(["書き換え済みクエリ"])
        out = asyncio.run(_engine(store, llm).rewrite("あれどうなった？"))
        assert out == "書き換え済みクエリ"

    def test_injects_current_datetime(self, store):
        llm = FakeLLM(["q"])
        asyncio.run(_engine(store, llm).rewrite("query"))
        assert "{current_datetime}" not in llm.calls[0]["system"]
        assert "現在の日時（JST）: 20" in llm.calls[0]["system"]

    def test_empty_response_falls_back(self, store):
        llm = FakeLLM(["  "])
        out = asyncio.run(_engine(store, llm).rewrite("元クエリ"))
        assert out == "元クエリ"

    def test_llm_error_falls_back(self, store):
        llm = FakeLLM([RuntimeError("API down")])
        out = asyncio.run(_engine(store, llm).rewrite("元クエリ"))
        assert out == "元クエリ"

    def test_uses_low_temperature(self, store):
        llm = FakeLLM(["q"])
        asyncio.run(_engine(store, llm).rewrite("query"))
        assert llm.calls[0]["temperature"] == 0.2

    def test_caps_rewriter_max_tokens(self, store):
        # 書き換えは短いので出力上限を絞る（残高不足で弾かれないように）
        llm = FakeLLM(["q"])
        asyncio.run(_engine(store, llm).rewrite("query"))
        assert llm.calls[0]["max_tokens"] == 256


# ── RagEngine.answer ────────────────────────────────────────────────────────

class TestAnswer:
    def test_full_flow(self, store):
        _seed(store)
        llm = FakeLLM(["書き換えクエリ", "わいわいちゃんの答え！っ"])
        result = asyncio.run(_engine(store, llm).answer("g1", "飲み会どうだった？"))
        assert result["answer"] == "わいわいちゃんの答え！っ"
        assert result["rewritten_query"] == "書き換えクエリ"
        assert result["sources"][0]["channel_name"] == "general"

    def test_context_injected_into_answer_prompt(self, store):
        _seed(store, chunk_text="渋谷で飲み会をした")
        llm = FakeLLM(["q", "答え"])
        asyncio.run(_engine(store, llm).answer("g1", "query"))
        answer_call = llm.calls[1]
        assert "渋谷で飲み会をした" in answer_call["system"]
        assert "{context}" not in answer_call["system"]
        assert "{guild_name}" not in answer_call["system"]

    def test_original_query_sent_to_answer_llm(self, store):
        _seed(store)
        llm = FakeLLM(["書き換えクエリ", "答え"])
        asyncio.run(_engine(store, llm).answer("g1", "元の質問"))
        assert llm.calls[1]["user"] == "元の質問"

    def test_rewritten_query_used_for_search(self, store):
        _seed(store)
        llm = FakeLLM(["書き換えクエリ", "答え"])
        embedder = FakeEmbedder()
        engine = RagEngine(CFG, store, embedder, llm)
        asyncio.run(engine.answer("g1", "元の質問"))
        assert embedder.embedded == ["書き換えクエリ"]

    def test_other_guild_data_not_visible(self, store):
        _seed(store, guild_id="other-guild", chunk_text="他サーバーの秘密")
        llm = FakeLLM(["q", "答え"])
        result = asyncio.run(_engine(store, llm).answer("g1", "query"))
        assert result["sources"] == []
        assert "他サーバーの秘密" not in llm.calls[1]["system"]

    def test_strips_think_from_answer(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答えのみ"])
        result = asyncio.run(_engine(store, llm).answer("g1", "query"))
        assert "<think>" not in result["answer"]

    def test_guild_name_injected_into_prompt(self, store):
        """リクエストで渡された guild_name がプロンプトに使われる。"""
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(
            _engine(store, llm).answer("g1", "query", guild_name="別のサーバー")
        )
        assert "別のサーバー" in llm.calls[1]["system"]

    def test_guild_name_falls_back_to_config(self, store):
        _seed(store)
        cfg = {"rag": {"top_k": 5, "guild_name": "コンフィグ名"}}
        llm = FakeLLM(["q", "答え"])
        engine = RagEngine(cfg, store, FakeEmbedder(), llm)
        asyncio.run(engine.answer("g1", "query"))
        assert "コンフィグ名" in llm.calls[1]["system"]

    def test_current_datetime_injected_into_answer_prompt(self, store):
        # OI-20: 回答プロンプトにも現在日時を入れる（過去ログの日付を「今日」と誤認しない）
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(_engine(store, llm).answer("g1", "query"))
        answer_system = llm.calls[1]["system"]
        assert "{current_datetime}" not in answer_system
        assert "今は 20" in answer_system  # _now_str() の "YYYY-..." が埋まっている


# ── マルチターン会話履歴（OI-10） ────────────────────────────────────────────

class TestConversationHistory:
    def test_history_passed_to_both_rewrite_and_answer(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        hist = [
            {"role": "user", "content": "前の質問"},
            {"role": "assistant", "content": "前の回答"},
        ]
        asyncio.run(_engine(store, llm).answer("g1", "それ詳しく", history=hist))
        assert llm.calls[0]["history"] == hist  # rewrite
        assert llm.calls[1]["history"] == hist  # answer

    def test_history_none_passes_empty_list(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(_engine(store, llm).answer("g1", "query"))
        assert llm.calls[0]["history"] == []
        assert llm.calls[1]["history"] == []

    def test_history_capped_to_max_turns(self, store):
        _seed(store)
        cfg = {"rag": {"top_k": 5, "history_max_turns": 2}}
        llm = FakeLLM(["q", "答え"])
        engine = RagEngine(cfg, store, FakeEmbedder(), llm)
        # 4ペア(8件)渡しても直近2ペア(4件)に丸められる
        hist = []
        for i in range(4):
            hist.append({"role": "user", "content": f"q{i}"})
            hist.append({"role": "assistant", "content": f"a{i}"})
        asyncio.run(engine.answer("g1", "query", history=hist))
        sent = llm.calls[1]["history"]
        assert len(sent) == 4
        assert sent[0]["content"] == "q2"

    def test_prep_history_drops_invalid_entries(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        hist = [
            {"role": "system", "content": "捨てられる"},   # role不正
            {"role": "user", "content": "   "},            # 空内容
            {"role": "assistant", "content": "残る"},
            {"foo": "bar"},                                # 不正な形
        ]
        asyncio.run(_engine(store, llm).answer("g1", "query", history=hist))
        sent = llm.calls[1]["history"]
        assert sent == [{"role": "assistant", "content": "残る"}]

    def test_history_max_turns_zero_disables(self, store):
        _seed(store)
        cfg = {"rag": {"top_k": 5, "history_max_turns": 0}}
        llm = FakeLLM(["q", "答え"])
        engine = RagEngine(cfg, store, FakeEmbedder(), llm)
        hist = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
        asyncio.run(engine.answer("g1", "query", history=hist))
        assert llm.calls[1]["history"] == []


# ── usage 計測（usage_recorder） ─────────────────────────────────────────────

_PRICING = {
    "google/gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "moonshotai/kimi-k2-0905": {"input": 0.60, "output": 2.50},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}


class TestUsageRecording:
    def _engine_with_recorder(self, store, llm):
        captured: list[dict] = []
        cfg = {"rag": {"top_k": 5}, "pricing": _PRICING}
        engine = RagEngine(
            cfg, store, FakeEmbedder(), llm, usage_recorder=captured.extend
        )
        return engine, captured

    def test_records_rewrite_embedding_answer(self, store):
        _seed(store)
        llm = FakeLLM([
            Completion("q", "google/gemini-2.5-flash", Usage(100, 20, 120)),
            Completion("答え", "moonshotai/kimi-k2-0905", Usage(5000, 300, 5300)),
        ])
        engine, captured = self._engine_with_recorder(store, llm)
        asyncio.run(engine.answer("g1", "質問", user_id="u1"))
        assert [e["kind"] for e in captured] == ["rewrite", "embedding", "answer"]
        assert all(e["guild_id"] == "g1" for e in captured)
        assert all(e["user_id"] == "u1" for e in captured)

    def test_answer_cost_computed_from_pricing(self, store):
        _seed(store)
        llm = FakeLLM([
            Completion("q", "google/gemini-2.5-flash", Usage(0, 0, 0)),
            Completion("答え", "moonshotai/kimi-k2-0905", Usage(5000, 300, 5300)),
        ])
        engine, captured = self._engine_with_recorder(store, llm)
        asyncio.run(engine.answer("g1", "質問"))
        answer_ev = next(e for e in captured if e["kind"] == "answer")
        # (5000*0.60 + 300*2.50) / 1e6 = 0.00375
        assert abs(answer_ev["cost_usd"] - 0.00375) < 1e-9

    def test_rewrite_failure_skips_its_usage(self, store):
        _seed(store)
        llm = FakeLLM([
            RuntimeError("down"),
            Completion("答え", "moonshotai/kimi-k2-0905", Usage(10, 5, 15)),
        ])
        engine, captured = self._engine_with_recorder(store, llm)
        asyncio.run(engine.answer("g1", "質問"))
        assert [e["kind"] for e in captured] == ["embedding", "answer"]

    def test_no_recorder_does_not_break(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        result = asyncio.run(_engine(store, llm).answer("g1", "質問"))
        assert result["answer"] == "答え"
