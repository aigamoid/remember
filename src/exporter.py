"""chunk_index からチャンネルごとにテキストファイルを出力する（Phase 3）。"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.db import fetch_chunks_by_channel


def _safe_filename(name: str) -> str:
    """ファイル名として使えない文字（絵文字・記号含む）を _ に置換する。"""
    return re.sub(r"[^\w\-]", "_", name, flags=re.UNICODE)


def run_exporter(conn: sqlite3.Connection, cfg: dict, run_id: str) -> int:
    """chunk_index からチャンネルごとにテキストファイルを output/ に出力する。"""
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    separator = "\n\n---\n\n"

    channels = conn.execute(
        "SELECT DISTINCT channel_id, channel_name FROM messages ORDER BY channel_name"
    ).fetchall()

    done = 0
    for channel_id, channel_name in channels:
        chunks = fetch_chunks_by_channel(conn, channel_id)
        if not chunks:
            print(f"  {channel_name}: チャンクなし, スキップ")
            continue

        # channel_id の先頭8文字でファイル名衝突を防ぐ
        safe_name = _safe_filename(channel_name)
        filename = output_dir / f"{safe_name}_{channel_id[:8]}_{today}.txt"
        filename.write_text(separator.join(chunks), encoding="utf-8")
        done += 1
        print(f"  {channel_name}: {len(chunks):,} チャンク → {filename}")

    return done
