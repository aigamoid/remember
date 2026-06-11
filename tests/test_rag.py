"""src/rag/ のテスト（フェイクLLM・フェイクembedder・インメモリQdrant）"""

from __future__ import annotations

import asyncio

import pytest
from qdrant_client import QdrantClient

from src.rag.engine import RagEngine
from src.rag.llm import strip_think
from src.rag.prompts import build_context
from src.vectorstore import VectorStore


class FakeLLM:
    """API を呼ばず固定応答を返す。呼び出し内容を記録する。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, model, system, user, temperature=0.7, max_tokens=None):
        self.calls.append(
            {"model": model, "system": system, "user": user, "temperature": temperature}
        )
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakeEmbedder:
    def __init__(self, dimensions: int = 4) -> None:
        self.dimensions = dimensions
        self.embedded: list[str] = []

    def embed(self, texts):
        self.embedded.extend(texts)
        return [[1.0] + [0.0] * (self.dimensions - 1) for _ in texts]

    def embed_one(self, text):
        return self.embed([text])[0]


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
