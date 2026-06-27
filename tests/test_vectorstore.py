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


def _payload(
    chunk_id: str, guild_id: str = "g1", text: str = "テスト", channel_id: str = "ch1"
) -> dict:
    return {
        "guild_id": guild_id,
        "chunk_id": chunk_id,
        "channel_id": channel_id,
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


class TestHybridSearch:
    """dense + BM25 sparse の RRF 融合（#54）。"""

    def test_upsert_with_sparse_and_count(self, store):
        store.ensure_collection()
        store.upsert(
            [_payload("c1"), _payload("c2")],
            [_vec(1.0), _vec(0.9)],
            [([101, 202], [2.0, 1.0]), ([303], [1.0])],
        )
        assert store.count() == 2

    def test_sparse_lane_boosts_keyword_match(self, store):
        # dense はほぼ同等（共線）にして、sparse 一致の差だけで順位が決まるようにする。
        store.ensure_collection()
        store.upsert(
            [_payload("c1", text="かにじる"), _payload("c2", text="別件")],
            [_vec(0.9), _vec(0.9)],
            [([101], [1.0]), ([303], [1.0])],
        )
        # クエリ sparse は c1 の語(101)だけにヒット → c1 が上位
        hits = store.search(
            "g1", _vec(0.9), top_k=5, sparse=([101], [1.0]), prefetch_k=10
        )
        assert hits[0]["chunk_id"] == "c1"

    def test_empty_sparse_falls_back_to_dense(self, store):
        store.ensure_collection()
        store.upsert([_payload("c1")], [_vec(1.0)], [([101], [1.0])])
        # sparse の indices が空なら dense-only パス（例外にならず結果が返る）
        hits = store.search("g1", _vec(1.0), top_k=5, sparse=([], []))
        assert len(hits) == 1
        assert hits[0]["chunk_id"] == "c1"

    def test_hybrid_respects_guild_filter(self, store):
        store.ensure_collection()
        store.upsert(
            [_payload("c1", guild_id="g1"), _payload("c2", guild_id="g2")],
            [_vec(1.0), _vec(1.0)],
            [([101], [1.0]), ([101], [1.0])],
        )
        hits = store.search("g1", _vec(1.0), top_k=10, sparse=([101], [1.0]))
        assert all(h["guild_id"] == "g1" for h in hits)

    def test_dense_only_still_works_without_sparse(self, store):
        # sparse 未指定なら従来どおり dense-only（後方互換）
        store.ensure_collection()
        store.upsert([_payload("c1")], [_vec(1.0)])
        hits = store.search("g1", _vec(1.0), top_k=5)
        assert len(hits) == 1


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


class TestDelete:
    def test_delete_by_guild_removes_only_that_guild(self, store):
        store.ensure_collection()
        store.upsert(
            [_payload("c1", guild_id="g1"), _payload("c2", guild_id="g2")],
            [_vec(1.0), _vec(0.5)],
        )
        store.delete_by_guild("g1")
        assert store.count("g1") == 0
        assert store.count("g2") == 1

    def test_delete_by_channel_removes_only_that_channel(self, store):
        store.ensure_collection()
        store.upsert(
            [
                _payload("c1", channel_id="ch1"),
                _payload("c2", channel_id="ch2"),
                _payload("c3", guild_id="g2", channel_id="ch1"),  # 別guildの同名ch
            ],
            [_vec(1.0), _vec(0.5), _vec(0.3)],
        )
        store.delete_by_channel("g1", "ch1")
        assert store.count("g1") == 1   # ch2 のみ残る
        assert store.count("g2") == 1   # 別guildは無傷

    def test_delete_on_missing_collection_is_noop(self, store):
        store.delete_by_guild("g1")          # 例外にならない
        store.delete_by_channel("g1", "ch1")  # 例外にならない


class TestDropCollection:
    def test_drop_then_recreate(self, store):
        store.ensure_collection()
        store.upsert([_payload("c1")], [_vec(1.0)])
        store.drop_collection()
        store.ensure_collection()
        assert store.count() == 0

    def test_drop_nonexistent_is_noop(self, store):
        store.drop_collection()  # 例外にならない
