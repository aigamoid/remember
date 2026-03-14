#!/usr/bin/env python3
"""
dry_run.py - Discord全チャンネルのメッセージ数をカウント（DBへの書き込みなし）

実行方法:
    python dry_run.py                     # メッセージ数カウントあり
    python dry_run.py --no-count          # チャンネル一覧のみ（カウントなし）
    docker compose run oracle python dry_run.py
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import discord
from dotenv import load_dotenv

from src.config import load_config

OUTPUT_FILE = Path("dry_run_result.txt")


async def _count_messages(channel: discord.TextChannel) -> int:
    """チャンネルのメッセージ数をカウントする（保存なし）"""
    count = 0
    async for _ in channel.history(limit=None, oldest_first=True):
        count += 1
        if count % 1000 == 0:
            print(f"  #{channel.name}: {count:,} 件取得中...", end="\r")
    return count


async def run(token: str, cfg: dict, no_count: bool) -> None:
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

        included = []
        excluded = []
        for ch in guild.text_channels:
            if ch.name in exclude_names or str(ch.id) in exclude_ids:
                excluded.append(ch)
            else:
                included.append(ch)

        lines: list[str] = []
        lines.append(f"サーバー: {guild.name} (ID: {guild.id})")
        lines.append(f"対象チャンネル: {len(included)} / 除外: {len(excluded)}")
        if excluded:
            lines.append("除外チャンネル: " + ", ".join(f"#{ch.name}" for ch in excluded))
        lines.append("")

        if no_count:
            lines.append(f"{'チャンネル名':<30} {'チャンネルID'}")
            lines.append("-" * 50)
            for ch in included:
                lines.append(f"#{ch.name:<29} {ch.id}")
        else:
            channel_counts: list[tuple[str, int, int]] = []
            for ch in included:
                print(f"  カウント中: #{ch.name} ...", end="\r")
                try:
                    n = await _count_messages(ch)
                except discord.Forbidden:
                    print(f"  #{ch.name}: アクセス権なし（スキップ）    ")
                    continue
                channel_counts.append((ch.name, ch.id, n))
                print(f"  #{ch.name}: {n:,} メッセージ              ")

            lines.append(f"{'チャンネル名':<30} {'チャンネルID':<22} {'メッセージ数':>10}")
            lines.append("-" * 65)
            for name, ch_id, n in channel_counts:
                lines.append(f"#{name:<29} {ch_id:<22} {n:>10,}")

            total = sum(n for _, _, n in channel_counts)
            estimated_chunks = sum(
                max(0, n - window_before - window_after) for _, _, n in channel_counts
            )
            lines.append("")
            lines.append("=" * 50)
            lines.append(f"総メッセージ数    : {total:,}")
            lines.append(f"推定チャンク数    : {estimated_chunks:,}  (ウィンドウ: -{window_before}/+{window_after})")
            lines.append(f"推定アップロード数: {estimated_chunks:,}  (Dify Knowledge API)")
            lines.append("=" * 50)

        output = "\n".join(lines) + "\n"
        OUTPUT_FILE.write_text(output, encoding="utf-8")
        print(f"\n結果を {OUTPUT_FILE} に出力しました")
        await client.close()

    try:
        await client.start(token)
    except discord.LoginFailure:
        print("エラー: DISCORD_TOKEN が無効です")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discord メッセージ数カウント（dry run）")
    parser.add_argument("--no-count", action="store_true", help="メッセージ数をカウントせずチャンネル一覧のみ出力")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("エラー: DISCORD_TOKEN が設定されていません (.env を確認してください)")
        sys.exit(1)

    cfg = load_config()
    asyncio.run(run(token, cfg, no_count=args.no_count))


if __name__ == "__main__":
    main()
