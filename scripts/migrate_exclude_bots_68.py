#!/usr/bin/env python3
"""migrate_exclude_bots_68.py - #68 既存データから Bot/Webhook 発言を一掃する一回限りの後始末。

新規メッセージは収集器（src/collectors/text_channel.py の _to_raw_message）が is_bot を
取得するため正しく除外されるが、**既存の messages は is_bot=0 のまま**（再クロールでは
ON CONFLICT DO NOTHING ＋ 増分取得のため過去行は更新されない）。

本スクリプトは:
  1. Discord API で既存 messages の各 author が Bot/Webhook か判定し is_bot=1 にマーク
     （自Bot だけでなくサードパーティ Bot/Webhook も一括是正。MAGI の P1 対応）。
  2. Bot を含んでいたギルドを **再チャンク → 再context → 再index**（Bot発言は人間アンカーの
     チャンクに混入しているため単純 DELETE では消えない）。
  3. Qdrant の該当ギルドのベクトルも作り直す（chunk_index 削除だけでは検索汚染が残る）。
  4. Bot 由来（subject が Bot 表示名）の pending 自動記憶を却下する。

判定不能な author_id（退会者・旧 Webhook 等）は保守的に is_bot=0 据え置き（人間の誤除外を
避ける）。必要なら --extra-bot-ids で手動補完する。

前提（本番相当環境で実行）:
    .env に DISCORD_TOKEN / OPENAI_API_KEY / OPENROUTER_API_KEY、config.yml が存在すること。
    docker compose 上なら: docker compose exec -e PYTHONPATH=/app worker \
        python3 scripts/migrate_exclude_bots_68.py [...]
実行:
    python scripts/migrate_exclude_bots_68.py                 # 全ギルド
    python scripts/migrate_exclude_bots_68.py --guild-id <id> # 1ギルドのみ
    python scripts/migrate_exclude_bots_68.py --dry-run       # 判定の確認のみ（DB/Qdrant変更なし）
    python scripts/migrate_exclude_bots_68.py --extra-bot-ids 123,456
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid

import discord
from dotenv import load_dotenv

from src.chunker import run_chunker
from src.config import load_config
from src.contextualizer import run_contextualizer
from src.db import (
    delete_chunks_for_guild,
    distinct_message_authors,
    get_connection,
    guild_ids_with_bot_messages,
    mark_authors_as_bot,
    reject_auto_memories_by_subject,
)
from src.embedder import Embedder
from src.indexer import run_indexer
from src.sparse import SparseEncoder
from src.vectorstore import VectorStore


async def _detect_bot_authors(
    token: str, authors: list[tuple[str, str]], extra_bot_ids: set[str]
) -> dict[str, tuple[bool, str]]:
    """Discord API で各 author を Bot 判定する。{author_id: (is_bot, author_name)} を返す。

    fetch_user は guild メンバーでなくても User を取得でき、その .bot で判定できる。
    取得不能（退会・旧 Webhook 等）は保守的に False（人間の誤除外を避ける）。
    """
    detected: dict[str, tuple[bool, str]] = {}
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:  # type: ignore[misc]
        try:
            for author_id, name in authors:
                if author_id in extra_bot_ids:
                    detected[author_id] = (True, name)
                    continue
                try:
                    user = await client.fetch_user(int(author_id))
                    detected[author_id] = (bool(user.bot), name)
                except Exception as e:  # noqa: BLE001
                    print(f"  [warn] author {author_id}({name}) 判定不可: "
                          f"{type(e).__name__} → is_bot=0 据え置き")
                    detected[author_id] = (False, name)
        finally:
            await client.close()

    await client.start(token)
    return detected


async def main_async(args: argparse.Namespace) -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("エラー: DISCORD_TOKEN が未設定です（.env を確認）")

    cfg = load_config()
    conn = get_connection()

    authors = distinct_message_authors(conn, args.guild_id)
    extra = {x for x in (args.extra_bot_ids or "").split(",") if x}
    print(f"既存 author 数: {len(authors)}（Discord API で Bot 判定します）")
    detected = await _detect_bot_authors(token, authors, extra)

    bot_ids = [aid for aid, (is_bot, _) in detected.items() if is_bot]
    bot_names = sorted({name for _, (is_bot, name) in detected.items() if is_bot})
    print(f"\nBot/Webhook 判定: {len(bot_ids)}/{len(authors)} 人")
    for aid in bot_ids:
        print(f"  - {detected[aid][1]} ({aid})")

    if args.dry_run:
        print("\n[dry-run] DB/Qdrant は変更せず終了しました。")
        conn.close()
        return

    marked = mark_authors_as_bot(conn, bot_ids)
    print(f"\nmessages.is_bot=1 にマーク: {marked} 件")
    rejected = reject_auto_memories_by_subject(conn, bot_names)
    print(f"Bot 由来の pending 自動記憶を却下: {rejected} 件")

    # --- 影響ギルドを再チャンク → 再context → 再index（Qdrantも作り直し）---
    qdrant_cfg = cfg.get("qdrant", {})
    emb_cfg = cfg.get("embedding", {})
    store = VectorStore(
        url=os.environ.get("QDRANT_URL")
        or qdrant_cfg.get("url", "http://localhost:6333"),
        collection=qdrant_cfg.get("collection", "waiwai_chunks"),
        vector_size=emb_cfg.get("dimensions", 1536),
    )
    embedder = Embedder(
        model=emb_cfg.get("model", "text-embedding-3-small"),
        dimensions=emb_cfg.get("dimensions", 1536),
    )
    # ハイブリッド検索（#54）が ON なら sparse も作り直す（OFFにすると検索が劣化するため）。
    sparse = None
    if cfg.get("rag", {}).get("hybrid", {}).get("enabled", False):
        sparse = SparseEncoder()

    if args.guild_id:
        targets = [args.guild_id]
    else:
        targets = guild_ids_with_bot_messages(conn)
    print(f"\n再ビルド対象ギルド: {len(targets)}（再contextはLLMコストが発生します）")

    for g in targets:
        print(f"\n== guild {g} 再ビルド ==")
        store.delete_by_guild(g)
        removed = delete_chunks_for_guild(conn, g)
        print(f"  旧チャンク削除: {removed} 件（Qdrantも削除）")
        run_id = str(uuid.uuid4())
        # run_contextualizer は内部で asyncio.run する（worker._ingest と同様）。
        # ここは既に asyncio.run 配下のループ内なので、ブロッキング呼び出しは
        # to_thread で別スレッドに逃がす（さもないと "asyncio.run() cannot be
        # called from a running event loop" でクラッシュする）。
        n_chunks = await asyncio.to_thread(run_chunker, conn, cfg, run_id, g)
        await asyncio.to_thread(run_contextualizer, conn, cfg, g)
        n_idx = await asyncio.to_thread(
            run_indexer, conn, cfg, store, embedder, g, False, sparse
        )
        print(f"  再チャンク {n_chunks} / 再index {n_idx}")

    conn.close()
    print("\n完了: Bot/Webhook 発言を取り込み（チャンク/ベクトル/自動記憶の抽出元）から一掃しました。")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="#68 既存データから Bot/Webhook 発言を一掃する後始末"
    )
    parser.add_argument("--guild-id", help="対象ギルドを1つに限定（未指定なら全ギルド）")
    parser.add_argument("--dry-run", action="store_true",
                        help="判定の確認のみ（DB/Qdrantを変更しない）")
    parser.add_argument("--extra-bot-ids",
                        help="判定不能なBot/Webhookを手動でBot扱いするauthor_id（カンマ区切り）")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
