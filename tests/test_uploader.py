"""src/uploader.py のテスト（インメモリ SQLite + requests モック）"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from src.db import _DDL, fetch_pending_channels, init_upload_state, reset_upload_errors
from src.formatter import format_message_line
from src.uploader import _build_channel_text, run_uploader


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
    channel_id: str = "ch1",
    channel_name: str = "雑談",
    author: str = "UserA",
    content: str = "hello",
    timestamp: str = "2024-05-03T12:13:00+00:00",
    has_attachment: int = 0,
) -> None:
    conn.execute(
        "INSERT INTO messages "
        "(id, channel_id, channel_name, author_id, author_name, content, timestamp, has_attachment) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (msg_id, channel_id, channel_name, "u1", author, content, timestamp, has_attachment),
    )


# --- formatter ---

class TestFormatMessageLine:
    def test_basic(self):
        line = format_message_line("UserA", "hello", "2024-05-03T12:00:00+00:00", False, 9)
        assert line == "[2024-05-03 21:00] UserA: hello"

    def test_attachment(self):
        line = format_message_line("UserA", "img", "2024-05-03T12:00:00+00:00", True, 9)
        assert "[添付ファイルあり]" in line

    def test_utc_offset(self):
        line = format_message_line("U", "x", "2024-01-01T00:00:00+00:00", False, 0)
        assert "[2024-01-01 00:00]" in line


# --- _build_channel_text ---

class TestBuildChannelText:
    def test_single_message(self, conn):
        _insert_msg(conn, "m1")
        conn.commit()
        name, text = _build_channel_text(conn, "ch1", "雑談", tz_offset=9)
        assert name == "雑談"
        assert "UserA" in text

    def test_order_by_timestamp(self, conn):
        _insert_msg(conn, "m1", timestamp="2024-05-03T12:00:00+00:00", content="first")
        _insert_msg(conn, "m2", timestamp="2024-05-03T13:00:00+00:00", content="second")
        conn.commit()
        _name, text = _build_channel_text(conn, "ch1", "雑談", tz_offset=9)
        assert text.index("first") < text.index("second")

    def test_multiple_channels(self, conn):
        _insert_msg(conn, "m1", channel_id="ch1", channel_name="雑談", content="ch1msg")
        _insert_msg(conn, "m2", channel_id="ch2", channel_name="開発", content="ch2msg")
        conn.commit()
        _name, text = _build_channel_text(conn, "ch1", "雑談", tz_offset=9)
        assert "ch1msg" in text
        assert "ch2msg" not in text


# --- init_upload_state ---

class TestInitUploadState:
    def test_creates_entries(self, conn):
        _insert_msg(conn, "m1", channel_id="ch1", channel_name="雑談")
        _insert_msg(conn, "m2", channel_id="ch2", channel_name="開発")
        conn.commit()
        count = init_upload_state(conn)
        assert count == 2
        channels = fetch_pending_channels(conn)
        assert len(channels) == 2

    def test_idempotent(self, conn):
        _insert_msg(conn, "m1")
        conn.commit()
        init_upload_state(conn)
        init_upload_state(conn)
        channels = fetch_pending_channels(conn)
        assert len(channels) == 1


# --- reset_upload_errors ---

class TestResetUploadErrors:
    def test_resets(self, conn):
        _insert_msg(conn, "m1")
        conn.commit()
        init_upload_state(conn)
        conn.execute("UPDATE upload_state SET status='error', error_message='fail'")
        conn.commit()
        count = reset_upload_errors(conn)
        assert count == 1
        channels = fetch_pending_channels(conn)
        assert len(channels) == 1

    def test_preserves_dataset_id(self, conn):
        _insert_msg(conn, "m1")
        conn.commit()
        init_upload_state(conn)
        conn.execute("UPDATE upload_state SET status='error', dataset_id='ds1'")
        conn.commit()
        reset_upload_errors(conn)
        row = conn.execute("SELECT dataset_id FROM upload_state").fetchone()
        assert row[0] == "ds1"


# --- run_uploader ---

def _make_cfg():
    return {
        "dify": {"api_endpoint": "http://localhost/v1"},
        "chunk": {"timezone_offset": 9},
    }


class TestRunUploader:
    @patch.dict("os.environ", {"DIFY_API_KEY": "test-key"})
    @patch("src.uploader._wait_for_indexing", return_value="completed")
    @patch("src.uploader.requests.post")
    def test_success(self, mock_post, _mock_wait, conn):
        _insert_msg(conn, "m1")
        conn.commit()

        resp_dataset = MagicMock(status_code=200)
        resp_dataset.json.return_value = {"id": "ds-1"}
        resp_doc = MagicMock(status_code=200)
        resp_doc.json.return_value = {"document": {"id": "doc-1"}, "batch": "b1"}
        mock_post.side_effect = [resp_dataset, resp_doc]

        done = run_uploader(conn, _make_cfg(), "run1")
        assert done == 1

        row = conn.execute("SELECT status, dataset_id, document_id FROM upload_state").fetchone()
        assert row[0] == "indexed"
        assert row[1] == "ds-1"
        assert row[2] == "doc-1"

    @patch.dict("os.environ", {"DIFY_API_KEY": "test-key"})
    @patch("src.uploader.requests.post")
    def test_error_marks_channel(self, mock_post, conn):
        _insert_msg(conn, "m1")
        conn.commit()

        mock_post.side_effect = Exception("API error")

        done = run_uploader(conn, _make_cfg(), "run1")
        assert done == 1

        row = conn.execute("SELECT status, error_message FROM upload_state").fetchone()
        assert row[0] == "error"
        assert "API error" in row[1]

    @patch.dict("os.environ", {"DIFY_API_KEY": "test-key"})
    @patch("src.uploader._wait_for_indexing", return_value="completed")
    @patch("src.uploader.requests.post")
    def test_reuses_dataset_id(self, mock_post, _mock_wait, conn):
        _insert_msg(conn, "m1")
        conn.commit()
        init_upload_state(conn)
        conn.execute("UPDATE upload_state SET status='pending', dataset_id='existing-ds'")
        conn.commit()

        resp_doc = MagicMock(status_code=200)
        resp_doc.json.return_value = {"document": {"id": "doc-1"}, "batch": "b1"}
        mock_post.side_effect = [resp_doc]

        run_uploader(conn, _make_cfg(), "run1")

        assert mock_post.call_count == 1  # document作成のみ、dataset作成なし
        row = conn.execute("SELECT dataset_id FROM upload_state").fetchone()
        assert row[0] == "existing-ds"

    @patch.dict("os.environ", {"DIFY_API_KEY": "test-key"})
    @patch("src.uploader._wait_for_indexing", return_value="completed")
    @patch("src.uploader.requests.post")
    def test_retry_errors(self, mock_post, _mock_wait, conn):
        _insert_msg(conn, "m1")
        conn.commit()
        init_upload_state(conn)
        conn.execute("UPDATE upload_state SET status='error', dataset_id='ds1'")
        conn.commit()

        resp_doc = MagicMock(status_code=200)
        resp_doc.json.return_value = {"document": {"id": "doc-1"}, "batch": "b1"}
        mock_post.side_effect = [resp_doc]

        done = run_uploader(conn, _make_cfg(), "run1", retry_errors=True)
        assert done == 1
        row = conn.execute("SELECT status FROM upload_state").fetchone()
        assert row[0] == "indexed"

    @patch.dict("os.environ", {"DIFY_API_KEY": "test-key"})
    def test_no_pending(self, conn):
        done = run_uploader(conn, _make_cfg(), "run1")
        assert done == 0
