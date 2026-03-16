#!/usr/bin/env python3
"""
uploader.py - チャンネルごとに Dify Knowledge API へアップロードする（Phase 3）

実行方法:
    python uploader.py
    python uploader.py --retry-errors
    docker compose run oracle python uploader.py
"""

import argparse
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from src.config import load_config
from src.db import init_db, log_run
from src.uploader import clean_datasets, run_uploader


def main() -> None:
    parser = argparse.ArgumentParser(description="Dify Knowledge API へアップロード")
    parser.add_argument("--retry-errors", action="store_true", help="エラーチャンネルを再試行")
    parser.add_argument("--clean", action="store_true", help="既存データセットを削除してから再アップロード")
    args = parser.parse_args()

    load_dotenv()
    cfg = load_config()

    db_path = Path("data/messages.db")
    conn = init_db(db_path)
    print(f"DB: {db_path}")

    run_id = str(uuid.uuid4())

    try:
        if args.clean:
            print("既存データセットを削除中...")
            clean_datasets(conn, cfg)

        done = run_uploader(conn, cfg, run_id, retry_errors=args.retry_errors)
        log_run(conn, run_id, "upload", "success", f"完了: {done:,} チャンネル")
        conn.commit()
        print(f"\n完了: {done:,} チャンネルをアップロード")
    except Exception as e:
        log_run(conn, run_id, "upload", "error", str(e))
        conn.commit()
        print(f"\nエラーが発生しました: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
