from __future__ import annotations

from pathlib import Path

import aiohttp
import discord
import psycopg

from src.collectors.base import MessageCollector
from src.db import (
    get_crawl_state,
    insert_attachment,
    insert_message,
    log_run,
    upsert_crawl_state,
)
from src.models import RawAttachment, RawMessage

_PROGRESS_INTERVAL = 500  # この件数ごとに進捗を表示


class TextChannelCollector(MessageCollector):
    """テキストチャンネルのメッセージを収集して DB に保存する。"""

    def __init__(
        self,
        guild: discord.Guild,
        cfg: dict,
    ) -> None:
        self._guild = guild
        self._guild_id = str(guild.id)
        crawl = cfg.get("crawl", {})
        self._exclude_names: set[str] = set(crawl.get("exclude_channels", []))
        self._exclude_ids: set[str] = {str(i) for i in crawl.get("exclude_channel_ids", [])}
        self._download: bool = crawl.get("download_attachments", False)
        self._attachment_dir = Path(crawl.get("attachment_dir", "data/attachments"))

    async def collect(
        self,
        conn: psycopg.Connection,
        run_id: str,
        channels: list[discord.TextChannel] | None = None,
    ) -> int:
        """channels 未指定なら guild の全テキストチャンネル（config の除外設定を適用）。
        指定時はそのリストだけを収集する（ワーカーが許可チャンネルを渡す）。"""
        total = 0
        if channels is None:
            channels = [
                ch for ch in self._guild.text_channels
                if ch.name not in self._exclude_names
                and str(ch.id) not in self._exclude_ids
            ]
        print(f"対象チャンネル: {len(channels)} ch")

        for ch in channels:
            count = await self._collect_channel(conn, run_id, ch)
            total += count

        return total

    async def _collect_channel(
        self,
        conn: psycopg.Connection,
        run_id: str,
        ch: discord.TextChannel,
    ) -> int:
        last_id = get_crawl_state(conn, str(ch.id))
        after = discord.Object(id=int(last_id)) if last_id else None

        count = 0
        last_message_id: str | None = last_id

        try:
            async for msg in ch.history(limit=None, oldest_first=True, after=after):
                raw = _to_raw_message(msg, self._guild_id)
                insert_message(conn, raw)

                for att in msg.attachments:
                    raw_att = RawAttachment(
                        id=str(att.id),
                        message_id=str(msg.id),
                        url=att.url,
                        filename=att.filename,
                        content_type=att.content_type,
                    )
                    insert_attachment(conn, raw_att)

                    if self._download:
                        await self._download_attachment(raw_att)

                last_message_id = str(msg.id)
                count += 1

                if count % _PROGRESS_INTERVAL == 0:
                    conn.commit()
                    print(f"  #{ch.name}: {count:,} 件保存中...")

        except discord.Forbidden:
            print(f"  #{ch.name}: アクセス権なし（スキップ）")
            log_run(conn, run_id, "crawl", "skip", f"Forbidden: #{ch.name}", self._guild_id)
            conn.commit()
            return count
        except discord.HTTPException as e:
            print(f"  #{ch.name}: HTTP エラー {e.status}（スキップ）")
            log_run(conn, run_id, "crawl", "error",
                    f"HTTPException {e.status}: #{ch.name}", self._guild_id)
            conn.commit()
            return count

        if last_message_id and last_message_id != last_id:
            upsert_crawl_state(conn, self._guild_id, str(ch.id), last_message_id)

        log_run(conn, run_id, "crawl", "success", f"#{ch.name}: {count} 件", self._guild_id)
        conn.commit()
        print(f"  #{ch.name}: {count:,} 件完了")
        return count

    async def _download_attachment(self, att: RawAttachment) -> None:
        self._attachment_dir.mkdir(parents=True, exist_ok=True)
        dest = self._attachment_dir / f"{att.id}_{att.filename}"
        if dest.exists():
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(att.url) as resp:
                    if resp.status == 200:
                        dest.write_bytes(await resp.read())
        except Exception:
            pass  # DLに失敗してもURLはDBに残るのでスキップ


def _to_raw_message(msg: discord.Message, guild_id: str) -> RawMessage:
    thread_id = str(msg.thread.id) if msg.thread else None
    thread_name = msg.thread.name if msg.thread else None
    reaction_count = sum(r.count for r in msg.reactions) if msg.reactions else 0

    return RawMessage(
        id=str(msg.id),
        guild_id=guild_id,
        channel_id=str(msg.channel.id),
        channel_name=msg.channel.name,
        author_id=str(msg.author.id),
        author_name=msg.author.display_name,
        content=msg.content,
        timestamp=msg.created_at.isoformat(),
        has_attachment=len(msg.attachments) > 0,
        is_pinned=msg.pinned,
        reaction_count=reaction_count,
        thread_id=thread_id,
        thread_name=thread_name,
    )
