#!/usr/bin/env python3
"""
crawler.py - Discord全チャンネルのメッセージを Postgres に収集する（Phase 1）

config.yml の guild_id を対象にした手動実行用（通常運用はワーカーが自動で行う）。

実行方法:
    python crawler.py
    docker compose run oracle python crawler.py
"""

import asyncio
import os
import sys
import uuid

import discord
from dotenv import load_dotenv

from src.collectors.text_channel import TextChannelCollector
from src.config import load_config
from src.db import get_connection, log_run


async def run(token: str, cfg: dict) -> None:
    guild_id: int = int(cfg["guild_id"])
    run_id = str(uuid.uuid4())

    conn = get_connection()

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        print(f"ログイン: {client.user}")

        guild = client.get_guild(guild_id)
        if guild is None:
            print(f"エラー: guild_id={guild_id} が見つかりません")
            await client.close()
            return

        print(f"サーバー: {guild.name}")

        collector = TextChannelCollector(guild, cfg)
        try:
            total = await collector.collect(conn, run_id)
            log_run(conn, run_id, "crawl", "success", f"完了: {total:,} 件")
            conn.commit()
            print(f"\n完了: 合計 {total:,} 件を保存しました")
        except Exception as e:
            log_run(conn, run_id, "crawl", "error", str(e))
            conn.commit()
            print(f"\nエラーが発生しました: {e}")
        finally:
            conn.close()
            await client.close()

    try:
        await client.start(token)
    except discord.LoginFailure:
        print("エラー: DISCORD_TOKEN が無効です")
        sys.exit(1)


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("エラー: DISCORD_TOKEN が設定されていません (.env を確認してください)")
        sys.exit(1)

    cfg = load_config()
    asyncio.run(run(token, cfg))


if __name__ == "__main__":
    main()
