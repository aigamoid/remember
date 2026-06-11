#!/usr/bin/env python3
"""
exporter.py - chunk_index からチャンネルごとにテキストファイルを出力する（Phase 3）

実行方法:
    python exporter.py
    docker compose run oracle python exporter.py
"""

import sys
import uuid

from dotenv import load_dotenv

from src.config import load_config
from src.db import get_connection, log_run
from src.exporter import run_exporter


def main() -> None:
    load_dotenv()
    cfg = load_config()

    conn = get_connection()

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
