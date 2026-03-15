#!/usr/bin/env python3
"""
chunker.py - SQLite のメッセージからチャンクを生成する（Phase 2）

実行方法:
    python chunker.py
    docker compose run oracle python chunker.py
"""

import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from src.chunker import run_chunker
from src.config import load_config
from src.db import count_chunks, init_db, log_run


def main() -> None:
    load_dotenv()
    cfg = load_config()

    db_path = Path("data/messages.db")
    conn = init_db(db_path)
    print(f"DB: {db_path}")

    run_id = str(uuid.uuid4())

    try:
        total = run_chunker(conn, cfg, run_id)
        pending = count_chunks(conn, status="pending")
        log_run(conn, run_id, "chunk", "success", f"完了: {total:,} 件")
        conn.commit()
        print(f"\n完了: {total:,} チャンク生成（pending: {pending:,} 件）")
    except Exception as e:
        log_run(conn, run_id, "chunk", "error", str(e))
        conn.commit()
        print(f"\nエラーが発生しました: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
