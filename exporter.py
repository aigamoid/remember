#!/usr/bin/env python3
"""
exporter.py - chunk_index からチャンネルごとにテキストファイルを出力する（Phase 3）

実行方法:
    python exporter.py
    docker compose run oracle python exporter.py
"""

import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from src.config import load_config
from src.db import init_db, log_run
from src.exporter import run_exporter


def main() -> None:
    load_dotenv()
    cfg = load_config()

    db_path = Path("data/messages.db")
    conn = init_db(db_path)
    print(f"DB: {db_path}")

    run_id = str(uuid.uuid4())

    try:
        done = run_exporter(conn, cfg, run_id)
        log_run(conn, run_id, "export", "success", f"完了: {done:,} チャンネル")
        conn.commit()
        print(f"\n完了: {done:,} チャンネルをエクスポート")
    except Exception as e:
        log_run(conn, run_id, "export", "error", str(e))
        conn.commit()
        print(f"\nエラーが発生しました: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
