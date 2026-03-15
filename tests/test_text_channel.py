"""src/collectors/text_channel.py のテスト（Discord オブジェクトをモックで代替）"""
from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.collectors.text_channel import TextChannelCollector, _to_raw_message
from src.db import _DDL


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(_DDL)
    conn.commit()
    return conn


def _make_discord_message(
    msg_id: int = 1,
    content: str = "テスト発言",
    channel_id: int = 100,
    channel_name: str = "general",
    author_id: int = 200,
    author_name: str = "Alice",
    pinned: bool = False,
    attachments: list | None = None,
    reactions: list | None = None,
) -> MagicMock:
    """discord.Message のモックを作る"""
    msg = MagicMock()
    msg.id = msg_id
    msg.content = content
    msg.channel.id = channel_id
    msg.channel.name = channel_name
    msg.author.id = author_id
    msg.author.display_name = author_name
    msg.pinned = pinned
    msg.attachments = attachments or []
    msg.reactions = reactions or []
    msg.thread = None

    # created_at は UTC の datetime として振る舞う
    from datetime import datetime, timezone
    msg.created_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    return msg


def _make_guild(channels: list) -> MagicMock:
    guild = MagicMock()
    guild.text_channels = channels
    return guild


def _make_channel(ch_id: int = 100, name: str = "general") -> MagicMock:
    ch = MagicMock()
    ch.id = ch_id
    ch.name = name
    return ch


# ── _to_raw_message（変換関数）────────────────────────────────

class TestToRawMessage(unittest.TestCase):
    def test_basic_conversion(self):
        msg = _make_discord_message(msg_id=42, content="Hello")
        raw = _to_raw_message(msg)
        assert raw.id == "42"
        assert raw.content == "Hello"
        assert raw.channel_name == "general"
        assert raw.author_name == "Alice"

    def test_timestamp_is_iso8601(self):
        msg = _make_discord_message()
        raw = _to_raw_message(msg)
        assert "2024-01-15" in raw.timestamp
        assert "12:00:00" in raw.timestamp

    def test_no_attachment(self):
        msg = _make_discord_message(attachments=[])
        raw = _to_raw_message(msg)
        assert raw.has_attachment is False

    def test_with_attachment(self):
        att = MagicMock()
        msg = _make_discord_message(attachments=[att])
        raw = _to_raw_message(msg)
        assert raw.has_attachment is True

    def test_reaction_count_sums_all_reactions(self):
        r1 = MagicMock()
        r1.count = 3
        r2 = MagicMock()
        r2.count = 2
        msg = _make_discord_message(reactions=[r1, r2])
        raw = _to_raw_message(msg)
        assert raw.reaction_count == 5

    def test_no_reactions_gives_zero(self):
        msg = _make_discord_message(reactions=[])
        raw = _to_raw_message(msg)
        assert raw.reaction_count == 0

    def test_thread_is_none_when_no_thread(self):
        msg = _make_discord_message()
        msg.thread = None
        raw = _to_raw_message(msg)
        assert raw.thread_id is None
        assert raw.thread_name is None


# ── TextChannelCollector.collect ──────────────────────────────

class TestTextChannelCollector(unittest.IsolatedAsyncioTestCase):
    def _make_cfg(self, exclude_ids: list | None = None) -> dict:
        return {
            "guild_id": 9999,
            "crawl": {
                "exclude_channels": [],
                "exclude_channel_ids": exclude_ids or [],
                "download_attachments": False,
            },
        }

    async def _run_collect(self, guild, cfg, conn) -> int:
        collector = TextChannelCollector(guild, cfg)
        return await collector.collect(conn, "run-test")

    async def test_collects_messages_from_channel(self):
        conn = _make_db()
        msg1 = _make_discord_message(msg_id=1, content="最初の発言")
        msg2 = _make_discord_message(msg_id=2, content="次の発言")

        ch = _make_channel(ch_id=100, name="general")
        async def mock_history(**kwargs):
            for m in [msg1, msg2]:
                yield m
        ch.history = mock_history

        guild = _make_guild([ch])
        total = await self._run_collect(guild, self._make_cfg(), conn)

        assert total == 2
        count = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
        assert count == 2

    async def test_excluded_channel_is_skipped(self):
        conn = _make_db()
        ch = _make_channel(ch_id=100, name="general")
        async def mock_history(**kwargs):
            yield _make_discord_message()
        ch.history = mock_history

        cfg = self._make_cfg(exclude_ids=[100])
        guild = _make_guild([ch])
        total = await self._run_collect(guild, cfg, conn)

        assert total == 0
        count = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
        assert count == 0

    async def test_forbidden_channel_is_skipped(self):
        """アクセス権のないチャンネルはスキップして続行する"""
        import discord
        conn = _make_db()

        ch = _make_channel(ch_id=100, name="private")
        async def mock_history_forbidden(**kwargs):
            raise discord.Forbidden(MagicMock(), "Forbidden")
            yield  # async generator にするための dummy
        ch.history = mock_history_forbidden

        guild = _make_guild([ch])
        total = await self._run_collect(guild, self._make_cfg(), conn)

        # エラーでも落ちない、件数は 0
        assert total == 0

    async def test_crawl_state_is_saved(self):
        """チャンネル完了後に crawl_state が更新される"""
        from src.db import get_crawl_state
        conn = _make_db()
        msg = _make_discord_message(msg_id=42)

        ch = _make_channel(ch_id=100, name="general")
        async def mock_history(**kwargs):
            yield msg
        ch.history = mock_history

        guild = _make_guild([ch])
        await self._run_collect(guild, self._make_cfg(), conn)

        last_id = get_crawl_state(conn, "100")
        assert last_id == "42"

    async def test_resumes_from_last_message(self):
        """再実行時は after= が渡されることを確認"""
        from src.db import upsert_crawl_state
        conn = _make_db()
        upsert_crawl_state(conn, "100", "99")  # 前回の最終ID

        received_after = {}

        ch = _make_channel(ch_id=100, name="general")
        async def mock_history(**kwargs):
            received_after["after"] = kwargs.get("after")
            return
            yield  # dummy
        ch.history = mock_history

        guild = _make_guild([ch])
        await self._run_collect(guild, self._make_cfg(), conn)

        assert received_after["after"] is not None
        assert received_after["after"].id == 99
