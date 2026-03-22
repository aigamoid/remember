"""src/exporter.py のテスト（インメモリ SQLite を使用）"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.db import _DDL, insert_chunk
from src.exporter import _safe_filename, run_exporter


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
    channel_name: str,
    content: str = "テスト内容",
    timestamp: str = "2024-01-01T00:00:00+00:00",
) -> None:
    conn.execute(
        "INSERT INTO messages "
        "(id, channel_id, channel_name, author_id, author_name, content, timestamp, has_attachment) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (msg_id, channel_id, channel_name, "u1", "user", content, timestamp, 0),
    )


# ── _safe_filename ──────────────────────────────────────────────────────────

class TestSafeFilename:
    def test_ascii_alphanumeric_unchanged(self):
        assert _safe_filename("general") == "general"

    def test_spaces_replaced(self):
        assert _safe_filename("my channel") == "my_channel"

    def test_emoji_replaced(self):
        result = _safe_filename("👋_ようこそ")
        assert "👋" not in result
        assert "_" in result

    def test_slash_replaced(self):
        assert "/" not in _safe_filename("a/b")

    def test_hyphen_preserved(self):
        assert _safe_filename("my-channel") == "my-channel"


# ── run_exporter ────────────────────────────────────────────────────────────

class TestRunExporter:
    def test_creates_output_directory(self, conn, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _insert_msg(conn, "m1", "ch1", "general")
        insert_chunk(conn, "c1", "m1", "ch1", "チャンクテキスト")
        conn.commit()

        run_exporter(conn, {}, "run-1")
        assert (tmp_path / "output").is_dir()

    def test_creates_file_per_channel(self, conn, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _insert_msg(conn, "m1", "ch1", "general")
        _insert_msg(conn, "m2", "ch2", "random")
        insert_chunk(conn, "c1", "m1", "ch1", "チャンクA")
        insert_chunk(conn, "c2", "m2", "ch2", "チャンクB")
        conn.commit()

        done = run_exporter(conn, {}, "run-1")
        assert done == 2
        files = list((tmp_path / "output").glob("*.txt"))
        assert len(files) == 2

    def test_file_contains_chunk_text(self, conn, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _insert_msg(conn, "m1", "ch1", "general")
        insert_chunk(conn, "c1", "m1", "ch1", "これはテストチャンクです")
        conn.commit()

        run_exporter(conn, {}, "run-1")
        files = list((tmp_path / "output").glob("*.txt"))
        assert len(files) == 1
        assert "これはテストチャンクです" in files[0].read_text(encoding="utf-8")

    def test_multiple_chunks_separated_by_divider(self, conn, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _insert_msg(conn, "m1", "ch1", "general", timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "general", timestamp="2024-01-01T02:00:00+00:00")
        insert_chunk(conn, "c1", "m1", "ch1", "チャンク1の内容")
        insert_chunk(conn, "c2", "m2", "ch1", "チャンク2の内容")
        conn.commit()

        run_exporter(conn, {}, "run-1")
        files = list((tmp_path / "output").glob("*.txt"))
        content = files[0].read_text(encoding="utf-8")
        assert "\n\n---\n\n" in content
        assert "チャンク1の内容" in content
        assert "チャンク2の内容" in content

    def test_channel_without_chunks_skipped(self, conn, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _insert_msg(conn, "m1", "ch1", "general")
        # chunk_index にデータを入れない
        conn.commit()

        done = run_exporter(conn, {}, "run-1")
        assert done == 0
        assert not list((tmp_path / "output").glob("*.txt"))

    def test_filename_includes_channel_id_prefix(self, conn, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _insert_msg(conn, "m1", "ABCDEF12345", "general")
        insert_chunk(conn, "c1", "m1", "ABCDEF12345", "テスト")
        conn.commit()

        run_exporter(conn, {}, "run-1")
        files = list((tmp_path / "output").glob("*.txt"))
        assert len(files) == 1
        assert "ABCDEF12" in files[0].name  # channel_id[:8]

    def test_empty_db_returns_zero(self, conn, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert run_exporter(conn, {}, "run-1") == 0
