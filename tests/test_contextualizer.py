"""src/contextualizer.py のテスト（インメモリ SQLite を使用）"""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.contextualizer import _get_preceding_messages, generate_context, run_contextualizer
from src.db import _DDL, fetch_chunks_for_context, insert_chunk, update_chunk_context
from src.db import add_context_text_column


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(_DDL)
    add_context_text_column(c)
    c.commit()
    yield c
    c.close()


def _insert_msg(
    conn: sqlite3.Connection,
    msg_id: str,
    channel_id: str,
    content: str,
    timestamp: str,
    author: str = "user",
    has_attachment: int = 0,
) -> None:
    conn.execute(
        "INSERT INTO messages "
        "(id, channel_id, channel_name, author_id, author_name, content, timestamp, has_attachment) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (msg_id, channel_id, "ch-test", "u1", author, content, timestamp, has_attachment),
    )


def _make_cfg(
    model: str = "gpt-4.1-nano",
    preceding_messages: int = 10,
    max_retries: int = 1,
    concurrency: int = 1,
) -> dict:
    return {
        "openai": {"api_key": "sk-test", "base_url": ""},
        "contextualizer": {
            "model": model,
            "preceding_messages": preceding_messages,
            "max_retries": max_retries,
            "retry_delay": 0.0,
            "concurrency": concurrency,
        },
        "chunk": {"timezone_offset": 9},
    }


# ── _get_preceding_messages ────────────────────────────────────────────────

class TestGetPrecedingMessages:
    def test_returns_preceding_in_ascending_order(self, conn):
        _insert_msg(conn, "m1", "ch1", "最初のメッセージ", "2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "二番目のメッセージ", "2024-01-01T00:01:00+00:00")
        _insert_msg(conn, "m3", "ch1", "アンカー", "2024-01-01T00:02:00+00:00")
        conn.commit()

        text, ts = _get_preceding_messages(conn, "m3", "ch1", n=10)

        assert "最初のメッセージ" in text
        assert "二番目のメッセージ" in text
        # アンカー自身は含まれない
        assert "アンカー" not in text
        # 時系列昇順（最初のメッセージが先）
        assert text.index("最初のメッセージ") < text.index("二番目のメッセージ")

    def test_returns_empty_when_no_preceding(self, conn):
        _insert_msg(conn, "m1", "ch1", "最初のメッセージ", "2024-01-01T00:00:00+00:00")
        conn.commit()

        text, ts = _get_preceding_messages(conn, "m1", "ch1", n=10)

        assert text == "（直前の会話なし）"

    def test_respects_n_limit(self, conn):
        for i in range(15):
            _insert_msg(conn, f"m{i}", "ch1", f"メッセージ{i}", f"2024-01-01T00:{i:02d}:00+00:00")
        anchor_id = "anchor"
        _insert_msg(conn, anchor_id, "ch1", "アンカー", "2024-01-01T00:20:00+00:00")
        conn.commit()

        text, _ = _get_preceding_messages(conn, anchor_id, "ch1", n=5)

        lines = text.strip().split("\n")
        assert len(lines) == 5

    def test_anchor_not_found_returns_unknown(self, conn):
        conn.commit()
        text, ts = _get_preceding_messages(conn, "nonexistent", "ch1", n=10)
        assert ts == "不明"
        assert text == "（直前の会話なし）"

    def test_same_timestamp_tiebreak(self, conn):
        """同一timestamp のメッセージを ID で tie-break する。"""
        _insert_msg(conn, "m_aaa", "ch1", "同秒メッセージ A", "2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m_bbb", "ch1", "同秒メッセージ B", "2024-01-01T00:00:00+00:00")
        # アンカーは m_bbb より大きい ID
        _insert_msg(conn, "m_ccc", "ch1", "アンカー", "2024-01-01T00:00:00+00:00")
        conn.commit()

        text, _ = _get_preceding_messages(conn, "m_ccc", "ch1", n=10)

        # m_ccc 自身は含まれない; m_aaa と m_bbb は含まれる
        assert "アンカー" not in text
        assert "同秒メッセージ A" in text
        assert "同秒メッセージ B" in text

    def test_different_channel_not_included(self, conn):
        _insert_msg(conn, "other_ch_msg", "ch_other", "別チャンネル", "2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "anchor", "ch1", "アンカー", "2024-01-01T00:01:00+00:00")
        conn.commit()

        text, _ = _get_preceding_messages(conn, "anchor", "ch1", n=10)
        assert "別チャンネル" not in text


# ── generate_context ───────────────────────────────────────────────────────

class TestGenerateContext:
    def test_calls_openai_and_returns_content(self):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "テスト用コンテキスト説明"
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = asyncio.run(generate_context(
            channel_name="general",
            anchor_timestamp="2024-01-01 09:00",
            preceding_text="直前の会話",
            chunk_text="対象チャンク",
            client=mock_client,
            model="gpt-4.1-nano",
        ))

        assert result == "テスト用コンテキスト説明"
        mock_client.chat.completions.create.assert_called_once()

    def test_strips_whitespace_from_response(self):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "  前後スペース付き  \n"
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = asyncio.run(generate_context(
            channel_name="general",
            anchor_timestamp="2024-01-01 09:00",
            preceding_text="",
            chunk_text="チャンク",
            client=mock_client,
            model="gpt-4.1-nano",
        ))

        assert result == "前後スペース付き"


# ── run_contextualizer ─────────────────────────────────────────────────────

class TestRunContextualizer:
    def test_processes_null_chunks(self, conn):
        _insert_msg(conn, "m1", "ch1", "hello world", "2024-01-01T00:00:00+00:00")
        insert_chunk(conn, "chunk1", "m1", "ch1", "hello world")
        conn.commit()

        cfg = _make_cfg()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "これはテスト会話のコンテキストです"

        with patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai_cls.return_value = mock_client

            done = run_contextualizer(conn, cfg)

        assert done == 1
        row = conn.execute(
            "SELECT context_text FROM chunk_index WHERE chunk_id = 'chunk1'"
        ).fetchone()
        assert row[0] == "これはテスト会話のコンテキストです"

    def test_skips_already_contextualized_chunks(self, conn):
        _insert_msg(conn, "m1", "ch1", "hello world", "2024-01-01T00:00:00+00:00")
        insert_chunk(conn, "chunk1", "m1", "ch1", "hello world")
        update_chunk_context(conn, "chunk1", "既存のコンテキスト")
        conn.commit()

        cfg = _make_cfg()
        with patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock()
            mock_openai_cls.return_value = mock_client

            done = run_contextualizer(conn, cfg)

        assert done == 0
        mock_client.chat.completions.create.assert_not_called()

    def test_records_error_on_api_failure(self, conn):
        _insert_msg(conn, "m1", "ch1", "hello world", "2024-01-01T00:00:00+00:00")
        insert_chunk(conn, "chunk1", "m1", "ch1", "hello world")
        conn.commit()

        cfg = _make_cfg()
        with patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=RuntimeError("接続失敗")
            )
            mock_openai_cls.return_value = mock_client

            done = run_contextualizer(conn, cfg)

        assert done == 0
        row = conn.execute(
            "SELECT error_message FROM chunk_index WHERE chunk_id = 'chunk1'"
        ).fetchone()
        assert row[0] is not None
        assert "接続失敗" in row[0]

    def test_authentication_error_raises_immediately(self, conn):
        """AuthenticationError は全件処理を abort して RuntimeError を raise する。"""
        import openai as _openai

        _insert_msg(conn, "m1", "ch1", "hello world", "2024-01-01T00:00:00+00:00")
        insert_chunk(conn, "chunk1", "m1", "ch1", "hello world")
        conn.commit()

        cfg = _make_cfg()
        with patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=_openai.AuthenticationError(
                    message="invalid key", response=MagicMock(), body={}
                )
            )
            mock_openai_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="認証エラー"):
                run_contextualizer(conn, cfg)

    def test_retry_succeeds_on_second_attempt(self, conn):
        """一時的エラー後にリトライして成功するケース。"""
        _insert_msg(conn, "m1", "ch1", "hello world", "2024-01-01T00:00:00+00:00")
        insert_chunk(conn, "chunk1", "m1", "ch1", "hello world")
        conn.commit()

        cfg = _make_cfg(max_retries=2)

        success_resp = MagicMock()
        success_resp.choices[0].message.content = "リトライ成功コンテキスト"

        with patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[RuntimeError("一時エラー"), success_resp]
            )
            mock_openai_cls.return_value = mock_client

            done = run_contextualizer(conn, cfg)

        assert done == 1
        row = conn.execute(
            "SELECT context_text FROM chunk_index WHERE chunk_id = 'chunk1'"
        ).fetchone()
        assert row[0] == "リトライ成功コンテキスト"

    def test_authentication_error_aborts_remaining_chunks(self, conn):
        """認証エラー発生後、未処理チャンクへの API 呼び出しが止まることを確認する。"""
        import openai as _openai

        for i in range(3):
            _insert_msg(conn, f"m{i}", "ch1", f"msg{i}", f"2024-01-01T00:0{i}:00+00:00")
            insert_chunk(conn, f"chunk{i}", f"m{i}", "ch1", f"msg{i}")
        conn.commit()

        cfg = _make_cfg(concurrency=1)  # 逐次実行でabortの効果を確認
        with patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=_openai.AuthenticationError(
                    message="invalid key", response=MagicMock(), body={}
                )
            )
            mock_openai_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="認証エラー"):
                run_contextualizer(conn, cfg)

        # concurrency=1 なので最大1回の API 呼び出しで止まるはず
        assert mock_client.chat.completions.create.call_count <= 1

    def test_processes_multiple_chunks(self, conn):
        for i in range(3):
            _insert_msg(conn, f"m{i}", "ch1", f"メッセージ{i}", f"2024-01-01T00:0{i}:00+00:00")
            insert_chunk(conn, f"chunk{i}", f"m{i}", "ch1", f"メッセージ{i}")
        conn.commit()

        cfg = _make_cfg()
        call_count = 0

        async def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.choices[0].message.content = f"コンテキスト{call_count}"
            return resp

        with patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=fake_create)
            mock_openai_cls.return_value = mock_client

            done = run_contextualizer(conn, cfg)

        assert done == 3


# ── fetch_chunks_for_context ───────────────────────────────────────────────

class TestFetchChunksForContext:
    def test_returns_only_null_context_chunks(self, conn):
        _insert_msg(conn, "m1", "ch1", "hello", "2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "world", "2024-01-01T00:01:00+00:00")
        insert_chunk(conn, "c1", "m1", "ch1", "hello")
        insert_chunk(conn, "c2", "m2", "ch1", "world")
        update_chunk_context(conn, "c1", "付与済みコンテキスト")
        conn.commit()

        results = fetch_chunks_for_context(conn)

        assert len(results) == 1
        assert results[0][0] == "c2"
