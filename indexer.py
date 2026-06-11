#!/usr/bin/env python3
"""
indexer.py - チャンクを embedding して Qdrant に登録する（Phase 4）

実行方法:
    python indexer.py            # 未インデックス（status != 'indexed'）のみ登録
    python indexer.py --all      # 全チャンクを再登録（上書き）
    python indexer.py --clean    # 対象guildの点を Qdrant から削除 + status リセット後に全登録
    docker compose run oracle python indexer.py

config.yml の guild_id を対象にした手動実行用（通常運用はワーカーが自動で行う）。
"""

import argparse
import os
import sys
import uuid

from dotenv import load_dotenv

from src.config import load_config
from src.db import get_connection, log_run, reset_chunk_index_status
from src.embedder import Embedder
from src.indexer import run_indexer
from src.vectorstore import VectorStore


def main() -> None:
    parser = argparse.ArgumentParser(description="チャンクを Qdrant に登録する")
    parser.add_argument("--all", action="store_true", help="全チャンクを再登録する")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Qdrant コレクションを削除し、status をリセットしてから全登録する",
    )
    args = parser.parse_args()

    load_dotenv()
    cfg = load_config()

    qdrant_cfg = cfg.get("qdrant", {})
    emb_cfg = cfg.get("embedding", {})
    # QDRANT_URL はコンテナ内からの接続用オーバーライド（compose では http://qdrant:6333）
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

    guild_id = str(cfg["guild_id"])
    conn = get_connection()

    if args.clean:
        store.delete_by_guild(guild_id)
        reset = reset_chunk_index_status(conn, guild_id)
        conn.commit()
        print(f"  Qdrant から guild の点を削除し、{reset:,} 件の status をリセットしました")

    run_id = str(uuid.uuid4())

    try:
        done = run_indexer(
            conn, cfg, store, embedder,
            guild_id=guild_id, include_indexed=args.all or args.clean,
        )
        log_run(conn, run_id, "index", "success", f"完了: {done:,} 件", guild_id)
        conn.commit()
        print(f"\n完了: {done:,} チャンクを Qdrant に登録")
    except Exception as e:
        log_run(conn, run_id, "index", "error", str(e))
        conn.commit()
        print(f"\nエラーが発生しました: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
