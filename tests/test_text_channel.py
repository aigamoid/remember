"""src/collectors/text_channel.py のテスト（Discordオブジェクトはモック・DBは実Postgres）"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.collectors.text_channel import TextChannelCollector, _to_raw_message
from src.db import get_crawl_state, upsert_crawl_state


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
    is_bot: bool = False,
) -> MagicMock:
    """discord.Message のモックを作る"""
    msg = MagicMock()
    msg.id = msg_id
    msg.content = content
    msg.channel.id = channel_id
    msg.channel.name = channel_name
    msg.author.id = author_id
    msg.author.display_name = author_name
    msg.author.bot = is_bot  # #68: 既定 False（MagicMock のままだと truthy になり is_bot 誤検出）
    msg.pinned = pinned
    msg.attachments = attachments or []
    msg.reactions = reactions or []
    msg.thread = None
    msg.created_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    return msg


def _make_guild(channels: list, guild_id: int = 9999) -> MagicMock:
    guild = MagicMock()
    guild.id = guild_id
    guild.text_channels = channels
    return guild


def _make_channel(ch_id: int = 100, name: str = "general") -> MagicMock:
    ch = MagicMock()
    ch.id = ch_id
    ch.name = name
    return ch


def _make_cfg(exclude_ids: list | None = None) -> dict:
    return {
        "guild_id": 9999,
        "crawl": {
            "exclude_channels": [],
            "exclude_channel_ids": exclude_ids or [],
            "download_attachments": False,
        },
    }


def _run_collect(guild, cfg, conn, channels=None) -> int:
    collector = TextChannelCollector(guild, cfg)
    return asyncio.run(collector.collect(conn, "run-test", channels=channels))


# ── _to_raw_message（変換関数）────────────────────────────────

class TestToRawMessage:
    def test_basic_conversion(self):
        msg = _make_discord_message(msg_id=42, content="Hello")
        raw = _to_raw_message(msg, "9999")
        assert raw.id == "42"
        assert raw.guild_id == "9999"
        assert raw.content == "Hello"
        assert raw.channel_name == "general"
        assert raw.author_name == "Alice"

    def test_timestamp_is_iso8601(self):
        msg = _make_discord_message()
        raw = _to_raw_message(msg, "9999")
        assert "2024-01-15" in raw.timestamp
        assert "12:00:00" in raw.timestamp

    def test_is_bot_false_for_human(self):  # #68
        msg = _make_discord_message(is_bot=False)
        raw = _to_raw_message(msg, "9999")
        assert raw.is_bot is False

    def test_is_bot_true_for_bot(self):  # #68: Bot/Webhook は author.bot=True
        msg = _make_discord_message(is_bot=True)
        raw = _to_raw_message(msg, "9999")
        assert raw.is_bot is True

    def test_no_attachment(self):
        msg = _make_discord_message(attachments=[])
        raw = _to_raw_message(msg, "9999")
        assert raw.has_attachment is False

    def test_with_attachment(self):
        att = MagicMock()
        msg = _make_discord_message(attachments=[att])
        raw = _to_raw_message(msg, "9999")
        assert raw.has_attachment is True

    def test_reaction_count_sums_all_reactions(self):
        r1 = MagicMock()
        r1.count = 3
        r2 = MagicMock()
        r2.count = 2
        msg = _make_discord_message(reactions=[r1, r2])
        raw = _to_raw_message(msg, "9999")
        assert raw.reaction_count == 5

    def test_thread_is_none_when_no_thread(self):
        msg = _make_discord_message()
        msg.thread = None
        raw = _to_raw_message(msg, "9999")
        assert raw.thread_id is None
        assert raw.thread_name is None


# ── TextChannelCollector.collect ──────────────────────────────

class TestTextChannelCollector:
    def test_collects_messages_from_channel(self, conn):
        msg1 = _make_discord_message(msg_id=1, content="最初の発言")
        msg2 = _make_discord_message(msg_id=2, content="次の発言")

        ch = _make_channel(ch_id=100, name="general")
        async def mock_history(**kwargs):
            for m in [msg1, msg2]:
                yield m
        ch.history = mock_history

        guild = _make_guild([ch])
        total = _run_collect(guild, _make_cfg(), conn)

        assert total == 2
        rows = conn.execute("SELECT count(*), min(guild_id) FROM messages").fetchone()
        assert rows[0] == 2
        assert rows[1] == "9999"  # guild_id が保存される

    def test_excluded_channel_is_skipped(self, conn):
        ch = _make_channel(ch_id=100, name="general")
        async def mock_history(**kwargs):
            yield _make_discord_message()
        ch.history = mock_history

        guild = _make_guild([ch])
        total = _run_collect(guild, _make_cfg(exclude_ids=[100]), conn)

        assert total == 0
        count = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
        assert count == 0

    def test_channels_argument_overrides_guild_channels(self, conn):
        """channels= 指定時は許可リストだけを収集する（ワーカーの opt-in 用）。"""
        allowed_ch = _make_channel(ch_id=100, name="allowed")
        async def history_allowed(**kwargs):
            yield _make_discord_message(msg_id=1, channel_id=100, channel_name="allowed")
        allowed_ch.history = history_allowed

        other_ch = _make_channel(ch_id=200, name="other")
        async def history_other(**kwargs):
            yield _make_discord_message(msg_id=2, channel_id=200, channel_name="other")
        other_ch.history = history_other

        guild = _make_guild([allowed_ch, other_ch])
        total = _run_collect(guild, _make_cfg(), conn, channels=[allowed_ch])

        assert total == 1
        names = {r[0] for r in conn.execute("SELECT channel_name FROM messages").fetchall()}
        assert names == {"allowed"}

    def test_forbidden_channel_is_skipped(self, conn):
        """アクセス権のないチャンネルはスキップして続行する"""
        import discord

        ch = _make_channel(ch_id=100, name="private")
        async def mock_history_forbidden(**kwargs):
            raise discord.Forbidden(MagicMock(), "Forbidden")
            yield  # async generator にするための dummy
        ch.history = mock_history_forbidden

        guild = _make_guild([ch])
        total = _run_collect(guild, _make_cfg(), conn)

        # エラーでも落ちない、件数は 0
        assert total == 0

    def test_crawl_state_is_saved(self, conn):
        """チャンネル完了後に crawl_state が更新される"""
        msg = _make_discord_message(msg_id=42)

        ch = _make_channel(ch_id=100, name="general")
        async def mock_history(**kwargs):
            yield msg
        ch.history = mock_history

        guild = _make_guild([ch])
        _run_collect(guild, _make_cfg(), conn)

        assert get_crawl_state(conn, "100") == "42"

    def test_resumes_from_last_message(self, conn):
        """再実行時は after= が渡されることを確認"""
        upsert_crawl_state(conn, "9999", "100", "99")  # 前回の最終ID
        conn.commit()

        received_after = {}

        ch = _make_channel(ch_id=100, name="general")
        async def mock_history(**kwargs):
            received_after["after"] = kwargs.get("after")
            return
            yield  # dummy
        ch.history = mock_history

        guild = _make_guild([ch])
        _run_collect(guild, _make_cfg(), conn)

        assert received_after["after"] is not None
        assert received_after["after"].id == 99
