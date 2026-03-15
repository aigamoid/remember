"""src/db.py のテスト（インメモリ SQLite を使用）"""

import sqlite3

import pytest

from src.db import (
    _DDL,
    get_crawl_state,
    insert_attachment,
    insert_message,
    log_run,
    upsert_crawl_state,
)
from src.models import RawAttachment, RawMessage


@pytest.fixture
def conn():
    """各テスト用のインメモリ SQLite 接続を提供する"""
    c = sqlite3.connect(":memory:")
    c.executescript(_DDL)
    c.commit()
    yield c
    c.close()


def _make_message(**kwargs) -> RawMessage:
    defaults = dict(
        id="msg-1",
        channel_id="ch-1",
        channel_name="general",
        author_id="user-1",
        author_name="Alice",
        content="テストメッセージ",
        timestamp="2024-01-15T12:00:00+00:00",
        has_attachment=False,
        is_pinned=False,
        reaction_count=0,
        thread_id=None,
        thread_name=None,
    )
    return RawMessage(**{**defaults, **kwargs})


def _make_attachment(**kwargs) -> RawAttachment:
    defaults = dict(
        id="att-1",
        message_id="msg-1",
        url="https://cdn.discordapp.com/attachments/1/2/photo.png",
        filename="photo.png",
        content_type="image/png",
    )
    return RawAttachment(**{**defaults, **kwargs})


# ── テーブル初期化 ─────────────────────────────────────────────

class TestInitDb:
    def test_all_tables_exist(self, conn):
        tables = {
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"messages", "attachments", "crawl_state", "chunk_index", "run_log"} <= tables

    def test_index_exists(self, conn):
        indexes = {
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        assert "idx_messages_channel_timestamp" in indexes


# ── insert_message ────────────────────────────────────────────

class TestInsertMessage:
    def test_saves_message(self, conn):
        insert_message(conn, _make_message())
        row = conn.execute("SELECT id, content FROM messages WHERE id = 'msg-1'").fetchone()
        assert row is not None
        assert row[1] == "テストメッセージ"

    def test_is_idempotent(self, conn):
        """同じ ID で2回 INSERT しても件数が増えない"""
        msg = _make_message()
        insert_message(conn, msg)
        insert_message(conn, msg)
        count = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
        assert count == 1

    def test_saves_empty_content(self, conn):
        """添付のみメッセージ（content=""）も保存できる"""
        insert_message(conn, _make_message(content="", has_attachment=True))
        row = conn.execute("SELECT content, has_attachment FROM messages WHERE id='msg-1'").fetchone()
        assert row[0] == ""
        assert row[1] == 1  # True → 1

    def test_saves_boolean_fields_as_integer(self, conn):
        insert_message(conn, _make_message(is_pinned=True, reaction_count=3))
        row = conn.execute("SELECT is_pinned, reaction_count FROM messages WHERE id='msg-1'").fetchone()
        assert row[0] == 1
        assert row[1] == 3

    def test_saves_thread_fields(self, conn):
        insert_message(conn, _make_message(thread_id="thr-1", thread_name="雑談スレ"))
        row = conn.execute("SELECT thread_id, thread_name FROM messages WHERE id='msg-1'").fetchone()
        assert row[0] == "thr-1"
        assert row[1] == "雑談スレ"

    def test_thread_fields_are_null_by_default(self, conn):
        insert_message(conn, _make_message())
        row = conn.execute("SELECT thread_id, thread_name FROM messages WHERE id='msg-1'").fetchone()
        assert row[0] is None
        assert row[1] is None


# ── insert_attachment ─────────────────────────────────────────

class TestInsertAttachment:
    def test_saves_attachment(self, conn):
        insert_message(conn, _make_message())
        insert_attachment(conn, _make_attachment())
        row = conn.execute("SELECT id, filename FROM attachments WHERE id='att-1'").fetchone()
        assert row is not None
        assert row[1] == "photo.png"

    def test_is_idempotent(self, conn):
        insert_message(conn, _make_message())
        att = _make_attachment()
        insert_attachment(conn, att)
        insert_attachment(conn, att)
        count = conn.execute("SELECT count(*) FROM attachments").fetchone()[0]
        assert count == 1

    def test_content_type_can_be_null(self, conn):
        insert_message(conn, _make_message())
        insert_attachment(conn, _make_attachment(content_type=None))
        row = conn.execute("SELECT content_type FROM attachments WHERE id='att-1'").fetchone()
        assert row[0] is None

    def test_local_path_starts_as_null(self, conn):
        """DL前は local_path が NULL"""
        insert_message(conn, _make_message())
        insert_attachment(conn, _make_attachment())
        row = conn.execute("SELECT local_path FROM attachments WHERE id='att-1'").fetchone()
        assert row[0] is None


# ── crawl_state ───────────────────────────────────────────────

class TestCrawlState:
    def test_returns_none_for_unknown_channel(self, conn):
        assert get_crawl_state(conn, "ch-unknown") is None

    def test_upsert_creates_entry(self, conn):
        upsert_crawl_state(conn, "ch-1", "msg-100")
        assert get_crawl_state(conn, "ch-1") == "msg-100"

    def test_upsert_updates_existing_entry(self, conn):
        upsert_crawl_state(conn, "ch-1", "msg-100")
        upsert_crawl_state(conn, "ch-1", "msg-200")
        assert get_crawl_state(conn, "ch-1") == "msg-200"

    def test_multiple_channels_are_independent(self, conn):
        upsert_crawl_state(conn, "ch-1", "msg-100")
        upsert_crawl_state(conn, "ch-2", "msg-999")
        assert get_crawl_state(conn, "ch-1") == "msg-100"
        assert get_crawl_state(conn, "ch-2") == "msg-999"


# ── log_run ───────────────────────────────────────────────────

class TestLogRun:
    def test_saves_log_entry(self, conn):
        log_run(conn, "run-1", "crawl", "success", "完了")
        row = conn.execute("SELECT run_id, phase, status, message FROM run_log").fetchone()
        assert row == ("run-1", "crawl", "success", "完了")

    def test_message_can_be_none(self, conn):
        log_run(conn, "run-1", "crawl", "success")
        row = conn.execute("SELECT message FROM run_log").fetchone()
        assert row[0] is None

    def test_multiple_logs_accumulate(self, conn):
        log_run(conn, "run-1", "crawl", "success", "ch-1 完了")
        log_run(conn, "run-1", "crawl", "error",   "ch-2 失敗")
        count = conn.execute("SELECT count(*) FROM run_log").fetchone()[0]
        assert count == 2
