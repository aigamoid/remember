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

from src import db, quota  # noqa: E402


def _next_channel_plan(conn, current: dict) -> dict | None:
    """現プランより多く（または無制限に）チャンネルを取り込める最安プラン（案内用）。"""
    cur_limit = current["channel_limit"]
    if cur_limit is None:
        return None  # 既に無制限
    for d in db.fetch_plan_defs(conn):  # sort_order 昇順＝最安側から
        cl = d["channel_limit"]
        if cl is None or cl > cur_limit:
            return d
    return None


def _unlimited_plan(conn) -> dict | None:
    """チャンネル数が無制限（channel_limit=None ＝ MAX）の最安プラン（allowall 案内用）。"""
    for d in db.fetch_plan_defs(conn):  # sort_order 昇順＝最安側から
        if d["channel_limit"] is None:
            return d
    return None


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

    async def fetch_plans(self) -> list[dict]:
        """全プラン定義を sort_order 順で返す（/oracle upgrade の一覧表示・OI-14 D）。"""
        return await self._call(db.fetch_plan_defs)

    async def guild_left(self, guild_id: str) -> None:
        """退出時: left_at を記録し、データ削除ジョブを投入する。"""
        def run(conn):
            db.mark_guild_left(conn, guild_id)
            db.enqueue_job(conn, guild_id, db.JOB_PURGE_GUILD, requested_by="guild_remove")

        await self._call(run)

    # ---- チャンネル許可（opt-in）----

    async def allow_channel(
        self, guild_id: str, channel_id: str, channel_name: str, allowed_by: str
    ) -> dict:
        """チャンネルを許可し取り込みジョブを投入する。

        プランのチャンネル数上限を超える新規許可は拒否する（OI-14 C-2）。
        戻り値:
          {"ok": True, "job_id": int|None}       … 許可OK（job_id None=取り込み重複）
          {"ok": False, "message": str}          … 上限超過で拒否（案内文つき）
        """
        def run(conn):
            existing = dict(db.fetch_allowed_channels(conn, guild_id))
            if channel_id not in existing:  # 新規許可のみ上限を見る（再許可は更新）
                plan = db.get_guild_plan(conn, guild_id)
                count = db.count_allowed_channels(conn, guild_id)
                if quota.channel_limit_exceeded(count, plan["channel_limit"]):
                    return {
                        "ok": False,
                        "message": quota.channel_limit_message(
                            plan["channel_limit"], _next_channel_plan(conn, plan)
                        ),
                    }
            db.allow_channel(conn, guild_id, channel_id, channel_name, allowed_by)
            job_id = db.enqueue_job(
                conn, guild_id, db.JOB_INGEST, requested_by=allowed_by
            )
            return {"ok": True, "job_id": job_id}

        return await self._call(run)

    async def allow_all_channels(
        self, guild_id: str, channels: list[tuple[str, str]], allowed_by: str
    ) -> dict:
        """全チャンネルを一括許可する（MAX＝チャンネル数無制限プラン限定）。

        channels: Botが読める全テキストチャンネルの [(channel_id, channel_name), ...]。
        MAX以外のプランは拒否する（有限上限と矛盾するため・OI-14 C-2 / OI-25）。
        既に許可済みのチャンネルはスキップし、新規許可があれば取り込みジョブを1件投入する。
        戻り値:
          {"ok": True, "added": int, "total": int, "job_id": int|None}
                                                  … job_id None=新規許可なし or 取り込み重複
          {"ok": False, "message": str}          … 非対応プランで拒否（案内文つき）
        """
        def run(conn):
            plan = db.get_guild_plan(conn, guild_id)
            if not quota.allow_all_allowed(plan["channel_limit"]):
                return {
                    "ok": False,
                    "message": quota.allow_all_denied_message(_unlimited_plan(conn)),
                }
            existing = dict(db.fetch_allowed_channels(conn, guild_id))
            added = 0
            for channel_id, channel_name in channels:
                if channel_id in existing:
                    continue  # 既に許可済みは更新不要
                db.allow_channel(conn, guild_id, channel_id, channel_name, allowed_by)
                added += 1
            job_id = None
            if added:  # 新規許可があるときだけ取り込みジョブを投入する
                job_id = db.enqueue_job(
                    conn, guild_id, db.JOB_INGEST, requested_by=allowed_by
                )
            return {
                "ok": True, "added": added, "total": len(channels), "job_id": job_id,
            }

        return await self._call(run)

    # ---- 同意ログ（公開/課金前の法務要件・#41 / OI-48）----

    async def has_consented(self, guild_id: str, terms_version: str) -> bool:
        """そのサーバーが現行の規約バージョンに同意済みかを返す。"""
        return await self._call(db.has_consented, guild_id, terms_version)

    async def record_consent(
        self,
        guild_id: str,
        admin_id: str,
        terms_version: str,
        scope: str,
        channels: list[dict] | None = None,
    ) -> None:
        """同意1件を記録する（scope='allow'|'allowall'）。"""
        await self._call(
            db.record_consent, guild_id, admin_id, terms_version, scope, channels
        )

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
