"""store.py - Bot用のDBアクセス層（src/db.py の薄い非同期ラッパー）。bot.py から使用。

スラッシュコマンド・guildイベントのたびに短命の接続を張って閉じる
（管理操作は低頻度なので接続プールは持たない）。
psycopg は同期APIのため、イベントループを塞がないよう asyncio.to_thread で実行する。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ローカル実行時（python bot.py）にリポジトリルートの src/ を import 可能にする。
# コンテナでは /app/src に配置されるため、この insert は無害。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402


class Store:
    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn

    async def _call(self, fn, *args):
        def run():
            conn = db.get_connection(self._dsn)
            try:
                return fn(conn, *args)
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    # ---- guild ライフサイクル ----

    async def register_guild(self, guild_id: str, guild_name: str) -> None:
        await self._call(db.upsert_guild, guild_id, guild_name)

    async def guild_left(self, guild_id: str) -> None:
        """退出時: left_at を記録し、データ削除ジョブを投入する。"""
        def run(conn):
            db.mark_guild_left(conn, guild_id)
            db.enqueue_job(conn, guild_id, db.JOB_PURGE_GUILD, requested_by="guild_remove")

        await self._call(run)

    # ---- チャンネル許可（opt-in）----

    async def allow_channel(
        self, guild_id: str, channel_id: str, channel_name: str, allowed_by: str
    ) -> int | None:
        """チャンネルを許可し、取り込みジョブを投入する。戻り値はジョブID（重複時 None）。"""
        def run(conn):
            db.allow_channel(conn, guild_id, channel_id, channel_name, allowed_by)
            return db.enqueue_job(
                conn, guild_id, db.JOB_INGEST, requested_by=allowed_by
            )

        return await self._call(run)

    async def deny_channel(
        self, guild_id: str, channel_id: str, requested_by: str
    ) -> bool:
        """許可を取り消し、チャンネルデータの削除ジョブを投入する。
        戻り値: 許可されていたチャンネルなら True。"""
        def run(conn):
            removed = db.deny_channel(conn, guild_id, channel_id)
            db.enqueue_job(
                conn, guild_id, db.JOB_PURGE_CHANNEL,
                channel_id=channel_id, requested_by=requested_by,
            )
            return removed

        return await self._call(run)

    # ---- sync / status ----

    async def enqueue_sync(self, guild_id: str, requested_by: str) -> int | None:
        return await self._call(
            lambda conn: db.enqueue_job(
                conn, guild_id, db.JOB_INGEST, requested_by=requested_by
            )
        )

    async def status(self, guild_id: str) -> dict:
        def run(conn):
            return {
                "allowed": db.fetch_allowed_channels(conn, guild_id),
                "messages": db.count_messages(conn, guild_id),
                "chunks": db.count_chunks(conn, guild_id=guild_id),
                "indexed": db.count_chunks(conn, status="indexed", guild_id=guild_id),
                "last_job": db.fetch_last_job(conn, guild_id),
            }

        return await self._call(run)
