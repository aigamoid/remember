"""moimoichan_Discordbot/store.py のテスト（実Postgres）

Store は src/db.py の薄い非同期ラッパー。allow_all_channels（/oracle allowall・OI-25）の
プラン判定と一括許可の挙動を、実DBに対して検証する。Store は自前で接続を張るため
TEST_DSN を渡し、セットアップ／プラン設定は conftest の conn フィクスチャ側で行う。
"""

from __future__ import annotations

import asyncio

from src.db import (
    count_allowed_channels,
    fetch_last_job,
    set_guild_plan,
    upsert_guild,
)

from moimoichan_Discordbot.store import Store
from tests.conftest import TEST_DSN

GUILD = "g-allowall"
CHANNELS = [("c1", "general"), ("c2", "random"), ("c3", "dev")]


def _store() -> Store:
    return Store(dsn=TEST_DSN)


class TestAllowAll:
    def test_max_plan_allows_all_channels(self, conn):
        upsert_guild(conn, GUILD, "テスト鯖")
        set_guild_plan(conn, GUILD, "max")
        conn.commit()

        result = asyncio.run(_store().allow_all_channels(GUILD, CHANNELS, "admin"))

        assert result["ok"] is True
        assert result["added"] == 3
        assert result["total"] == 3
        assert result["job_id"] is not None
        assert count_allowed_channels(conn, GUILD) == 3
        # 取り込みジョブが1件積まれる
        job = fetch_last_job(conn, GUILD)
        assert job is not None and job["kind"] == "ingest"

    def test_free_plan_is_rejected(self, conn):
        upsert_guild(conn, GUILD, "テスト鯖")
        conn.commit()  # プラン未設定＝free（channel_limit=1）

        result = asyncio.run(_store().allow_all_channels(GUILD, CHANNELS, "admin"))

        assert result["ok"] is False
        assert "MAX" in result["message"]
        # 拒否時はチャンネルを一切許可しない
        assert count_allowed_channels(conn, GUILD) == 0

    def test_pro_plan_is_rejected(self, conn):
        upsert_guild(conn, GUILD, "テスト鯖")
        set_guild_plan(conn, GUILD, "pro")  # channel_limit=10（有限）
        conn.commit()

        result = asyncio.run(_store().allow_all_channels(GUILD, CHANNELS, "admin"))

        assert result["ok"] is False
        assert count_allowed_channels(conn, GUILD) == 0

    def test_already_allowed_channels_are_skipped(self, conn):
        upsert_guild(conn, GUILD, "テスト鯖")
        set_guild_plan(conn, GUILD, "max")
        conn.commit()
        # 1回目で全部許可
        asyncio.run(_store().allow_all_channels(GUILD, CHANNELS, "admin"))

        # 2回目: 新規なし → added=0・ジョブは積まない
        result = asyncio.run(_store().allow_all_channels(GUILD, CHANNELS, "admin"))

        assert result["ok"] is True
        assert result["added"] == 0
        assert result["total"] == 3
        assert result["job_id"] is None
        assert count_allowed_channels(conn, GUILD) == 3

    def test_partial_new_channels_added(self, conn):
        upsert_guild(conn, GUILD, "テスト鯖")
        set_guild_plan(conn, GUILD, "max")
        conn.commit()
        asyncio.run(_store().allow_all_channels(GUILD, CHANNELS[:1], "admin"))  # c1のみ

        result = asyncio.run(_store().allow_all_channels(GUILD, CHANNELS, "admin"))

        assert result["added"] == 2  # c2, c3 が新規
        assert result["total"] == 3
        # 1回目で積んだ ingest ジョブが pending のため2回目は重複排除で None になる
        # （二重取り込み防止＝正しい挙動）。チャンネルは全部許可済みになっている。
        assert result["job_id"] is None
        assert count_allowed_channels(conn, GUILD) == 3
        assert fetch_last_job(conn, GUILD)["kind"] == "ingest"
