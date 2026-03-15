from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

from src.db import insert_chunk


def generate_chunk_id(anchor_msg_id: str, window_before: int, window_after: int) -> str:
    """MD5(anchor_msg_id:window_before:window_after) で chunk_id を生成する。"""
    raw = f"{anchor_msg_id}:{window_before}:{window_after}"
    return hashlib.md5(raw.encode()).hexdigest()


def _build_chunk_text(
    rows: list[tuple],
    tz_offset: int = 9,
) -> str:
    """ウィンドウ内のメッセージをテキスト化する。タイムスタンプは UTC→指定オフセットに変換。"""
    tz = timezone(timedelta(hours=tz_offset))
    lines = []
    for _, author, content, ts, has_att in rows:
        dt = datetime.fromisoformat(ts).astimezone(tz)
        ts_display = dt.strftime("%Y-%m-%d %H:%M")
        line = f"[{ts_display}] {author}: {content}"
        if has_att:
            line += " [添付ファイルあり]"
        lines.append(line)
    return "\n".join(lines)


def _process_channel(
    conn: sqlite3.Connection,
    channel_id: str,
    window_before: int,
    window_after: int,
    min_len: int,
    tz_offset: int,
) -> int:
    """1チャンネル分を処理してアンカー候補件数を返す。"""
    rows = conn.execute(
        "SELECT id, author_name, content, timestamp, has_attachment FROM messages "
        "WHERE channel_id = ? ORDER BY timestamp ASC",
        (channel_id,),
    ).fetchall()

    count = 0
    for i, (msg_id, _, content, _, has_attachment) in enumerate(rows):
        if len(content) < min_len and not has_attachment:
            continue
        window = rows[max(0, i - window_before) : i + window_after + 1]
        chunk_text = _build_chunk_text(window, tz_offset)
        chunk_id = generate_chunk_id(msg_id, window_before, window_after)
        insert_chunk(conn, chunk_id, msg_id, channel_id, chunk_text)
        count += 1
    return count


def run_chunker(conn: sqlite3.Connection, cfg: dict, run_id: str) -> int:
    """messages テーブルをチャンネルごとに処理し、chunk_index に保存する。候補件数を返す。"""
    chunk_cfg = cfg.get("chunk", {})
    window_before: int = chunk_cfg.get("window_before", 2)
    window_after: int  = chunk_cfg.get("window_after", 2)
    min_len: int       = chunk_cfg.get("min_content_length", 4)
    tz_offset: int     = chunk_cfg.get("timezone_offset", 9)

    total = 0
    channel_ids = [
        row[0] for row in
        conn.execute(
            "SELECT DISTINCT channel_id FROM messages ORDER BY channel_id"
        ).fetchall()
    ]

    for channel_id in channel_ids:
        count = _process_channel(conn, channel_id, window_before, window_after, min_len, tz_offset)
        total += count
        conn.commit()
        print(f"  channel {channel_id}: {count:,} チャンク生成")

    return total
