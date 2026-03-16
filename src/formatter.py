"""メッセージ→テキスト変換の共通関数。chunker / uploader から使用。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def format_message_line(
    author: str,
    content: str,
    timestamp: str,
    has_attachment: bool,
    tz_offset: int = 9,
) -> str:
    """1メッセージを '[YYYY-MM-DD HH:MM] author: content' 形式に変換する。"""
    tz = timezone(timedelta(hours=tz_offset))
    dt = datetime.fromisoformat(timestamp).astimezone(tz)
    ts_display = dt.strftime("%Y-%m-%d %H:%M")
    line = f"[{ts_display}] {author}: {content}"
    if has_attachment:
        line += " [添付ファイルあり]"
    return line
