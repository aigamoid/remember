"""src/chunker.py のテスト（インメモリ SQLite を使用）"""

from __future__ import annotations

import sqlite3

import pytest

from src.chunker import _build_chunk_text, generate_chunk_id, run_chunker
from src.db import _DDL, count_chunks, insert_chunk


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(_DDL)
    c.commit()
    yield c
    c.close()


def _insert_msg(
    conn: sqlite3.Connection,
    msg_id: str,
    channel_id: str,
    content: str,
    has_attachment: int = 0,
    author: str = "user",
    timestamp: str = "2024-01-01T00:00:00+00:00",
) -> None:
    conn.execute(
        "INSERT INTO messages "
        "(id, channel_id, channel_name, author_id, author_name, content, timestamp, has_attachment) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (msg_id, channel_id, "ch", "u1", author, content, timestamp, has_attachment),
    )


def _make_cfg(window_before: int = 2, window_after: int = 2, min_content_length: int = 4) -> dict:
    return {"chunk": {
        "window_before": window_before,
        "window_after": window_after,
        "min_content_length": min_content_length,
        "timezone_offset": 9,
    }}


# ── generate_chunk_id ──────────────────────────────────────────────────────

class TestGenerateChunkId:
    def test_returns_32_char_hex(self):
        result = generate_chunk_id("msg-1", 2, 2)
        assert isinstance(result, str)
        assert len(result) == 32

    def test_is_deterministic(self):
        assert generate_chunk_id("msg-1", 2, 2) == generate_chunk_id("msg-1", 2, 2)

    def test_differs_by_anchor(self):
        assert generate_chunk_id("msg-1", 2, 2) != generate_chunk_id("msg-2", 2, 2)

    def test_differs_by_window_before(self):
        assert generate_chunk_id("msg-1", 2, 2) != generate_chunk_id("msg-1", 3, 2)

    def test_differs_by_window_after(self):
        assert generate_chunk_id("msg-1", 2, 2) != generate_chunk_id("msg-1", 2, 3)


# ── _build_chunk_text ──────────────────────────────────────────────────────

class TestBuildChunkText:
    def test_timestamp_converted_to_jst(self):
        rows = [("id1", "UserA", "hello", "2024-01-01T12:00:00+00:00", 0)]
        text = _build_chunk_text(rows, tz_offset=9)
        assert "[2024-01-01 21:00]" in text  # UTC+9

    def test_contains_author_and_content(self):
        rows = [("id1", "UserA", "てすと", "2024-01-01T00:00:00+00:00", 0)]
        text = _build_chunk_text(rows, tz_offset=9)
        assert "UserA" in text
        assert "てすと" in text

    def test_attachment_flag_appended(self):
        rows = [("id1", "UserA", "画像です", "2024-01-01T00:00:00+00:00", 1)]
        text = _build_chunk_text(rows, tz_offset=9)
        assert "[添付ファイルあり]" in text

    def test_no_attachment_flag_when_false(self):
        rows = [("id1", "UserA", "テキストのみ", "2024-01-01T00:00:00+00:00", 0)]
        text = _build_chunk_text(rows, tz_offset=9)
        assert "[添付ファイルあり]" not in text

    def test_multiple_rows_joined_by_newline(self):
        rows = [
            ("id1", "UserA", "一行目", "2024-01-01T00:00:00+00:00", 0),
            ("id2", "UserB", "二行目", "2024-01-01T00:01:00+00:00", 0),
        ]
        text = _build_chunk_text(rows, tz_offset=9)
        assert text.count("\n") == 1


# ── insert_chunk / count_chunks ────────────────────────────────────────────

class TestInsertChunk:
    def test_saves_with_pending_status(self, conn):
        insert_chunk(conn, "cid1", "mid1", "ch1", "text")
        row = conn.execute(
            "SELECT anchor_msg_id, channel_id, status FROM chunk_index WHERE chunk_id='cid1'"
        ).fetchone()
        assert row is not None
        assert row[0] == "mid1"
        assert row[1] == "ch1"
        assert row[2] == "pending"

    def test_is_idempotent(self, conn):
        insert_chunk(conn, "cid1", "mid1", "ch1", "text")
        insert_chunk(conn, "cid1", "mid1", "ch1", "text")
        assert count_chunks(conn) == 1

    def test_count_chunks_no_filter(self, conn):
        insert_chunk(conn, "c1", "m1", "ch1", "a")
        insert_chunk(conn, "c2", "m2", "ch1", "b")
        assert count_chunks(conn) == 2

    def test_count_chunks_by_status(self, conn):
        insert_chunk(conn, "c1", "m1", "ch1", "a")
        conn.execute("UPDATE chunk_index SET status='indexed' WHERE chunk_id='c1'")
        insert_chunk(conn, "c2", "m2", "ch1", "b")
        assert count_chunks(conn, status="pending") == 1
        assert count_chunks(conn, status="indexed") == 1

    def test_count_chunks_unknown_status_returns_zero(self, conn):
        insert_chunk(conn, "c1", "m1", "ch1", "a")
        assert count_chunks(conn, status="no_such_status") == 0


# ── run_chunker ────────────────────────────────────────────────────────────

class TestRunChunker:
    def test_generates_chunks_for_valid_messages(self, conn):
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ", timestamp="2024-01-01T00:01:00+00:00")
        _insert_msg(conn, "m2", "ch1", "これも十分な長さです", timestamp="2024-01-01T00:02:00+00:00")
        conn.commit()

        total = run_chunker(conn, _make_cfg(), "run-1")
        assert total == 2
        assert count_chunks(conn) == 2

    def test_short_content_without_attachment_skipped(self, conn):
        _insert_msg(conn, "m1", "ch1", "ab", has_attachment=0)  # 2文字 < min_len=4
        conn.commit()
        assert run_chunker(conn, _make_cfg(), "run-1") == 0

    def test_short_content_with_attachment_not_skipped(self, conn):
        _insert_msg(conn, "m1", "ch1", "ab", has_attachment=1)  # 添付あり → スキップしない
        conn.commit()
        assert run_chunker(conn, _make_cfg(), "run-1") == 1

    def test_empty_messages_returns_zero(self, conn):
        assert run_chunker(conn, _make_cfg(), "run-1") == 0

    def test_channel_boundary_isolation(self, conn):
        _insert_msg(conn, "a1", "ch-A", "チャンネルAのメッセージ", timestamp="2024-01-01T00:01:00+00:00")
        _insert_msg(conn, "b1", "ch-B", "チャンネルBのメッセージ", timestamp="2024-01-01T00:02:00+00:00")
        conn.commit()

        run_chunker(conn, _make_cfg(), "run-1")
        anchors = {r[0] for r in conn.execute("SELECT anchor_msg_id FROM chunk_index").fetchall()}
        assert "a1" in anchors
        assert "b1" in anchors

    def test_idempotency_db_count_unchanged_on_rerun(self, conn):
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ")
        conn.commit()

        run_chunker(conn, _make_cfg(), "run-1")
        first_count = count_chunks(conn)
        run_chunker(conn, _make_cfg(), "run-2")
        assert count_chunks(conn) == first_count

    def test_rerun_returns_same_candidate_count(self, conn):
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ")
        conn.commit()

        first = run_chunker(conn, _make_cfg(), "run-1")
        second = run_chunker(conn, _make_cfg(), "run-2")
        assert first == second == 1

    def test_chunk_text_saved_in_db(self, conn):
        _insert_msg(conn, "m1", "ch1", "テスト内容", author="UserA",
                    timestamp="2024-01-01T12:00:00+00:00")
        conn.commit()

        run_chunker(conn, _make_cfg(), "run-1")
        row = conn.execute("SELECT chunk_text FROM chunk_index").fetchone()
        assert row is not None
        assert "UserA" in row[0]
        assert "テスト内容" in row[0]
        assert "[2024-01-01 21:00]" in row[0]  # UTC→JST(+9)
