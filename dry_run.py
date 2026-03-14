#!/usr/bin/env python3
"""
dry_run.py - Discord全チャンネルのメッセージ数をカウント（DBへの書き込みなし）

実行方法:
    python dry_run.py
    docker compose run oracle python dry_run.py
"""

import asyncio
import os
import sys

import discord
from dotenv import load_dotenv

from src.config import load_config


async def _count_messages(channel: discord.TextChannel) -> int:
    """チャンネルのメッセージ数をカウントする（保存なし）"""
    count = 0
    async for _ in channel.history(limit=None, oldest_first=True):
        count += 1
        if count % 1000 == 0:
            print(f"  #{channel.name}: {count:,} 件取得中...", end="\r")
    return count


async def run(token: str, cfg: dict) -> None:
    guild_id: int = int(cfg["guild_id"])
    crawl = cfg.get("crawl", {})
    exclude_names: set[str] = set(crawl.get("exclude_channels", []))
    exclude_ids: set[str] = {str(i) for i in crawl.get("exclude_channel_ids", [])}
    window_before: int = cfg.get("chunk", {}).get("window_before", 2)
    window_after: int = cfg.get("chunk", {}).get("window_after", 2)

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        guild = client.get_guild(guild_id)
        if guild is None:
            print(f"エラー: guild_id={guild_id} が見つかりません")
            await client.close()
            return

        print(f"\nサーバー: {guild.name} (ID: {guild.id})")

        included = []
        excluded = []
        for ch in guild.text_channels:
            if ch.name in exclude_names or str(ch.id) in exclude_ids:
                excluded.append(ch)
            else:
                included.append(ch)

        print(f"対象チャンネル: {len(included)} / 除外: {len(excluded)}")
        if excluded:
            print("  除外チャンネル: " + ", ".join(f"#{ch.name}" for ch in excluded))
        print()

        channel_counts: list[tuple[str, int]] = []
        for ch in included:
            print(f"  カウント中: #{ch.name} ...", end="\r")
            try:
                n = await _count_messages(ch)
            except discord.Forbidden:
                print(f"  #{ch.name}: アクセス権なし（スキップ）    ")
                continue
            channel_counts.append((ch.name, n))
            print(f"  #{ch.name}: {n:,} メッセージ              ")

        total = sum(n for _, n in channel_counts)
        estimated_chunks = sum(
            max(0, n - window_before - window_after) for _, n in channel_counts
        )

        print("\n" + "=" * 50)
        print(f"総メッセージ数    : {total:,}")
        print(f"推定チャンク数    : {estimated_chunks:,}  (ウィンドウ: -{window_before}/+{window_after})")
        print(f"推定アップロード数: {estimated_chunks:,}  (Dify Knowledge API)")
        print("=" * 50)
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
