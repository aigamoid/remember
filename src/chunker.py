from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone

from src.db import insert_chunk
from src.formatter import format_message_line


def generate_chunk_id(anchor_msg_id: str) -> str:
    """MD5(anchor_msg_id) で chunk_id を生成する。"""
    return hashlib.md5(anchor_msg_id.encode()).hexdigest()


def _build_chunk_text(
    rows: list[tuple],
    tz_offset: int = 9,
) -> str:
    """ウィンドウ内のメッセージをテキスト化する。タイムスタンプは UTC→指定オフセットに変換。"""
    lines = [
        format_message_line(author, content, ts, bool(has_att), tz_offset)
        for _, author, content, ts, has_att in rows
    ]
    return "\n".join(lines)


def _is_noise(content: str, has_attachment: bool, min_len: int) -> bool:
    """ノイズメッセージか判定する。True なら除去対象。"""
    if has_attachment:
        return False
    if len(content.strip()) < min_len:
        return True
    if re.match(r'^https?://\S+\s*$', content.strip()):
        return True
    if re.match(r'^@(here|everyone)\s*$', content.strip()):
        return True
    return False


def _flush_buffer(
    conn: sqlite3.Connection,
    buffer: list[tuple],
    channel_id: str,
    tz_offset: int,
) -> None:
    """バッファの内容を chunk_index に書き込む。buffer は空でないこと。"""
    anchor_msg_id = buffer[0][0]
    chunk_id = generate_chunk_id(anchor_msg_id)
    chunk_text = _build_chunk_text(buffer, tz_offset)
    insert_chunk(conn, chunk_id, anchor_msg_id, channel_id, chunk_text)


def _process_channel(
    conn: sqlite3.Connection,
    channel_id: str,
    time_gap_minutes: int,
    max_chunk_messages: int,
    min_len: int,
    tz_offset: int,
    short_reply_max_chars: int = 10,
) -> int:
    """1チャンネル分を時間ギャップ方式で処理し、生成チャンク数を返す。"""
    rows = conn.execute(
        "SELECT id, author_name, content, timestamp, has_attachment FROM messages "
        "WHERE channel_id = ? ORDER BY timestamp ASC",
        (channel_id,),
    ).fetchall()

    buffer: list[tuple] = []
    prev_ts: datetime | None = None
    chunk_count = 0

    for row in rows:
        msg_id, _, content, timestamp_str, has_attachment = row
        curr_ts = datetime.fromisoformat(timestamp_str).replace(tzinfo=timezone.utc)

        stripped = content.strip()
        if not stripped:
            continue

        is_short_reply = len(stripped) <= short_reply_max_chars and not has_attachment

        # 短文 + バッファあり + ギャップ未満 → 直前チャンクに吸収（@here/@everyone は除外）
        if is_short_reply and buffer and prev_ts is not None:
            gap_minutes = (curr_ts - prev_ts).total_seconds() / 60
            if gap_minutes < time_gap_minutes:
                if not re.match(r'^@(here|everyone)\s*$', stripped):
                    buffer.append(row)
                    # prev_ts 更新なし（ギャップ計算を通常メッセージ基準に保つ）
                    if len(buffer) >= max_chunk_messages:
                        _flush_buffer(conn, buffer, channel_id, tz_offset)
                        chunk_count += 1
                        buffer = []
                    continue

        # 通常のノイズフィルター
        if _is_noise(content, bool(has_attachment), min_len):
            continue

        # 時間ギャップ・件数で分割判定
        should_split = False
        if prev_ts is not None:
            gap_minutes = (curr_ts - prev_ts).total_seconds() / 60
            if gap_minutes >= time_gap_minutes:
                should_split = True
        if len(buffer) >= max_chunk_messages:
            should_split = True

        if should_split and buffer:
            _flush_buffer(conn, buffer, channel_id, tz_offset)
            chunk_count += 1
            buffer = []

        buffer.append(row)
        prev_ts = curr_ts

    if buffer:
        _flush_buffer(conn, buffer, channel_id, tz_offset)
        chunk_count += 1

    return chunk_count


def run_chunker(conn: sqlite3.Connection, cfg: dict, run_id: str) -> int:
    """messages テーブルをチャンネルごとに処理し、chunk_index に保存する。生成チャンク数を返す。"""
    chunk_cfg = cfg.get("chunk", {})
    time_gap_minutes: int = chunk_cfg.get("time_gap_minutes", 60)
    max_chunk_messages: int = chunk_cfg.get("max_chunk_messages", 30)
    min_len: int = chunk_cfg.get("min_content_length", 10)
    short_reply_max_chars: int = chunk_cfg.get("short_reply_max_chars", 10)
    tz_offset: int = chunk_cfg.get("timezone_offset", 9)

    total = 0
    channel_ids = [
        row[0] for row in
        conn.execute(
            "SELECT DISTINCT channel_id FROM messages ORDER BY channel_id"
        ).fetchall()
    ]

    for channel_id in channel_ids:
        count = _process_channel(
            conn, channel_id, time_gap_minutes, max_chunk_messages, min_len, tz_offset,
            short_reply_max_chars,
        )
        total += count
        conn.commit()
        print(f"  channel {channel_id}: {count:,} チャンク生成")

    return total
