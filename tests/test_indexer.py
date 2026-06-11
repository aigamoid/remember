"""src/indexer.py のテスト（インメモリ SQLite + インメモリ Qdrant + フェイク embedder）"""

from __future__ import annotations

import sqlite3

import pytest
from qdrant_client import QdrantClient

from src.db import _DDL, fetch_chunks_for_indexing, insert_chunk
from src.indexer import build_embed_text, run_indexer
from src.vectorstore import VectorStore


class FakeEmbedder:
    """API を呼ばず固定次元のベクトルを返す。呼び出し回数と入力を記録する。"""

    def __init__(self, dimensions: int = 4) -> None:
        self.dimensions = dimensions
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[1.0] + [0.0] * (self.dimensions - 1) for _ in texts]


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(_DDL)
    c.commit()
    yield c
    c.close()


@pytest.fixture
def store():
    return VectorStore(
        client=QdrantClient(":memory:"), collection="test", vector_size=4
    )


CFG = {"guild_id": 12345, "embedding": {"batch_size": 2}}


def _insert_msg(conn, msg_id, channel_id="ch1", channel_name="general"):
    conn.execute(
        "INSERT INTO messages "
        "(id, channel_id, channel_name, author_id, author_name, content, timestamp) "
        "VALUES (?,?,?,?,?,?,?)",
        (msg_id, channel_id, channel_name, "u1", "user", "内容",
         "2024-01-01T00:00:00+00:00"),
    )


def _insert_chunk_with_msg(conn, chunk_id, msg_id, context_text=None):
    _insert_msg(conn, msg_id)
    insert_chunk(conn, chunk_id, msg_id, "ch1", f"チャンク{chunk_id}")
    if context_text:
        conn.execute(
            "UPDATE chunk_index SET context_text=? WHERE chunk_id=?",
            (context_text, chunk_id),
        )


class TestBuildEmbedText:
    def test_without_context(self):
        assert build_embed_text("本文", None) == "本文"

    def test_with_context(self):
        assert build_embed_text("本文", "文脈") == "文脈\n\n本文"


class TestRunIndexer:
    def test_indexes_pending_chunks(self, conn, store):
        _insert_chunk_with_msg(conn, "c1", "m1")
        _insert_chunk_with_msg(conn, "c2", "m2")
        conn.commit()

        done = run_indexer(conn, CFG, store, FakeEmbedder())
        assert done == 2
        assert store.count("12345") == 2

    def test_marks_chunks_indexed(self, conn, store):
        _insert_chunk_with_msg(conn, "c1", "m1")
        conn.commit()

        run_indexer(conn, CFG, store, FakeEmbedder())
        status = conn.execute(
            "SELECT status FROM chunk_index WHERE chunk_id='c1'"
        ).fetchone()[0]
        assert status == "indexed"

    def test_second_run_skips_indexed(self, conn, store):
        _insert_chunk_with_msg(conn, "c1", "m1")
        conn.commit()

        run_indexer(conn, CFG, store, FakeEmbedder())
        done = run_indexer(conn, CFG, store, FakeEmbedder())
        assert done == 0

    def test_include_indexed_reindexes_all(self, conn, store):
        _insert_chunk_with_msg(conn, "c1", "m1")
        conn.commit()

        run_indexer(conn, CFG, store, FakeEmbedder())
        done = run_indexer(conn, CFG, store, FakeEmbedder(), include_indexed=True)
        assert done == 1
        assert store.count() == 1  # 上書きなので増えない

    def test_context_text_included_in_embedding(self, conn, store):
        _insert_chunk_with_msg(conn, "c1", "m1", context_text="この会話の文脈")
        conn.commit()

        embedder = FakeEmbedder()
        run_indexer(conn, CFG, store, embedder)
        assert "この会話の文脈\n\nチャンクc1" in embedder.calls[0]

    def test_payload_contains_metadata(self, conn, store):
        _insert_chunk_with_msg(conn, "c1", "m1")
        conn.commit()

        run_indexer(conn, CFG, store, FakeEmbedder())
        hits = store.search("12345", [1.0, 0.0, 0.0, 0.0], top_k=1)
        payload = hits[0]
        assert payload["guild_id"] == "12345"
        assert payload["channel_name"] == "general"
        assert payload["anchor_timestamp"] == "2024-01-01T00:00:00+00:00"

    def test_batching_respects_batch_size(self, conn, store):
        for i in range(5):
            _insert_chunk_with_msg(conn, f"c{i}", f"m{i}")
        conn.commit()

        embedder = FakeEmbedder()
        run_indexer(conn, CFG, store, embedder)  # batch_size=2
        assert [len(c) for c in embedder.calls] == [2, 2, 1]

    def test_empty_db_returns_zero(self, conn, store):
        assert run_indexer(conn, CFG, store, FakeEmbedder()) == 0


class TestFetchChunksForIndexing:
    def test_chunk_without_message_excluded(self, conn):
        # anchor メッセージが messages に無いチャンクは JOIN で除外される
        insert_chunk(conn, "orphan", "no-such-msg", "ch1", "孤立チャンク")
        conn.commit()
        assert fetch_chunks_for_indexing(conn) == []
