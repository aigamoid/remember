#!/usr/bin/env python3
"""migrate_sqlite_to_pg.py - 旧SQLite（data/messages.db）のデータを Postgres に移行する

単一guild時代のデータに guild_id を付与しながらコピーする（1回だけ実行する想定・冪等）。
guilds / allowed_channels も既存データから登録するので、移行後すぐ検索・syncできる。

実行方法:
    docker compose up -d postgres
    python scripts/migrate_sqlite_to_pg.py                # guild_id は config.yml から
    python scripts/migrate_sqlite_to_pg.py --guild-id 123 --db data/messages.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from src.config import load_config
from src.db import get_connection

_BATCH = 1000


def _copy(sqlite_conn, pg_conn, select_sql: str, insert_sql: str, transform) -> int:
    rows = sqlite_conn.execute(select_sql).fetchall()
    with pg_conn.cursor() as cur:
        for start in range(0, len(rows), _BATCH):
            cur.executemany(insert_sql, [transform(r) for r in rows[start:start + _BATCH]])
    pg_conn.commit()
    return len(rows)


def migrate(sqlite_path: Path, guild_id: str, guild_name: str) -> None:
    if not sqlite_path.exists():
        sys.exit(f"エラー: {sqlite_path} が見つかりません")

    sq = sqlite3.connect(sqlite_path)
    pg = get_connection()

    n = _copy(
        sq, pg,
        "SELECT id, channel_id, channel_name, author_id, author_name, content, "
        "timestamp, has_attachment, is_pinned, reaction_count, thread_id, thread_name "
        "FROM messages",
        "INSERT INTO messages (id, guild_id, channel_id, channel_name, author_id, "
        "author_name, content, timestamp, has_attachment, is_pinned, reaction_count, "
        "thread_id, thread_name) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (id) DO NOTHING",
        lambda r: (r[0], guild_id) + tuple(r[1:]),
    )
    print(f"messages: {n:,} 件")

    n = _copy(
        sq, pg,
        "SELECT id, message_id, url, filename, content_type, local_path, description, "
        "described_at FROM attachments",
        "INSERT INTO attachments (id, message_id, url, filename, content_type, "
        "local_path, description, described_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (id) DO NOTHING",
        tuple,
    )
    print(f"attachments: {n:,} 件")

    n = _copy(
        sq, pg,
        "SELECT channel_id, last_message_id, crawled_at FROM crawl_state",
        "INSERT INTO crawl_state (channel_id, guild_id, last_message_id, crawled_at) "
        "VALUES (%s,%s,%s,%s) ON CONFLICT (channel_id) DO NOTHING",
        lambda r: (r[0], guild_id, r[1], r[2]),
    )
    print(f"crawl_state: {n:,} 件")

    # status / context_text を保持して移行（indexed のチャンクは再処理されない）
    n = _copy(
        sq, pg,
        "SELECT chunk_id, anchor_msg_id, channel_id, chunk_text, context_text, "
        "status, indexed_at, error_message FROM chunk_index",
        "INSERT INTO chunk_index (chunk_id, guild_id, anchor_msg_id, channel_id, "
        "chunk_text, context_text, status, indexed_at, error_message) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (chunk_id) DO NOTHING",
        lambda r: (r[0], guild_id) + tuple(r[1:]),
    )
    print(f"chunk_index: {n:,} 件")

    pg.execute(
        "INSERT INTO guilds (guild_id, guild_name, joined_at) "
        "VALUES (%s, %s, now()::text) ON CONFLICT (guild_id) DO NOTHING",
        (guild_id, guild_name),
    )
    cur = pg.execute(
        """
        INSERT INTO allowed_channels (guild_id, channel_id, channel_name, allowed_by, allowed_at)
        SELECT DISTINCT guild_id, channel_id, channel_name, 'migration', now()::text
        FROM messages WHERE guild_id = %s
        ON CONFLICT (guild_id, channel_id) DO NOTHING
        """,
        (guild_id,),
    )
    pg.commit()
    print(f"guilds: 1 件 / allowed_channels: {cur.rowcount:,} 件")

    sq.close()
    pg.close()
    print("\n移行完了")


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite → Postgres データ移行")
    parser.add_argument("--db", default="data/messages.db", help="移行元SQLiteのパス")
    parser.add_argument("--guild-id", default=None, help="付与する guild_id（省略時は config.yml）")
    parser.add_argument("--guild-name", default="", help="guilds に登録するサーバー名")
    args = parser.parse_args()

    load_dotenv()
    guild_id = args.guild_id
    guild_name = args.guild_name
    if guild_id is None:
        cfg = load_config()
        guild_id = str(cfg["guild_id"])
        guild_name = guild_name or cfg.get("rag", {}).get("guild_name", "")

    migrate(Path(args.db), guild_id, guild_name)


if __name__ == "__main__":
    main()
