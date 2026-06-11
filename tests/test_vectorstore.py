"""src/vectorstore.py のテスト（Qdrant インメモリモードを使用）"""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from src.vectorstore import VectorStore


def _vec(x: float, size: int = 4) -> list[float]:
    """先頭要素のみ x、残り0のテスト用ベクトル。"""
    return [x] + [0.0] * (size - 1)


@pytest.fixture
def store():
    return VectorStore(
        client=QdrantClient(":memory:"), collection="test", vector_size=4
    )


def _payload(chunk_id: str, guild_id: str = "g1", text: str = "テスト") -> dict:
    return {
        "guild_id": guild_id,
        "chunk_id": chunk_id,
        "channel_id": "ch1",
        "channel_name": "general",
        "chunk_text": text,
        "context_text": None,
        "anchor_timestamp": "2024-01-01T00:00:00+00:00",
    }


class TestEnsureCollection:
    def test_creates_collection(self, store):
        store.ensure_collection()
        assert store.count() == 0

    def test_idempotent(self, store):
        store.ensure_collection()
        store.upsert([_payload("c1")], [_vec(1.0)])
        store.ensure_collection()  # 2回目でもデータは消えない
        assert store.count() == 1


class TestUpsert:
    def test_upsert_and_count(self, store):
        store.ensure_collection()
        store.upsert([_payload("c1"), _payload("c2")], [_vec(1.0), _vec(0.5)])
        assert store.count() == 2

    def test_same_chunk_id_overwrites(self, store):
        store.ensure_collection()
        store.upsert([_payload("c1", text="旧")], [_vec(1.0)])
        store.upsert([_payload("c1", text="新")], [_vec(1.0)])
        assert store.count() == 1
        hits = store.search("g1", _vec(1.0), top_k=1)
        assert hits[0]["chunk_text"] == "新"


class TestSearch:
    def test_returns_payload_with_score(self, store):
        store.ensure_collection()
        store.upsert([_payload("c1", text="こんにちは")], [_vec(1.0)])
        hits = store.search("g1", _vec(1.0), top_k=5)
        assert len(hits) == 1
        assert hits[0]["chunk_text"] == "こんにちは"
        assert hits[0]["score"] > 0.99

    def test_guild_filter_excludes_other_guilds(self, store):
        store.ensure_collection()
        store.upsert(
            [_payload("c1", guild_id="g1"), _payload("c2", guild_id="g2")],
            [_vec(1.0), _vec(1.0)],
        )
        hits = store.search("g1", _vec(1.0), top_k=10)
        assert len(hits) == 1
        assert hits[0]["guild_id"] == "g1"

    def test_top_k_limits_results(self, store):
        store.ensure_collection()
        payloads = [_payload(f"c{i}") for i in range(5)]
        vectors = [_vec(1.0 - i * 0.1) for i in range(5)]
        store.upsert(payloads, vectors)
        assert len(store.search("g1", _vec(1.0), top_k=3)) == 3


class TestCount:
    def test_count_by_guild(self, store):
        store.ensure_collection()
        store.upsert(
            [_payload("c1", guild_id="g1"), _payload("c2", guild_id="g2")],
            [_vec(1.0), _vec(0.5)],
        )
        assert store.count("g1") == 1
        assert store.count("g2") == 1
        assert store.count() == 2


class TestDropCollection:
    def test_drop_then_recreate(self, store):
        store.ensure_collection()
        store.upsert([_payload("c1")], [_vec(1.0)])
        store.drop_collection()
        store.ensure_collection()
        assert store.count() == 0

    def test_drop_nonexistent_is_noop(self, store):
        store.drop_collection()  # 例外にならない
