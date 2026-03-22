"""メッセージ→テキスト変換の共通関数。chunker / contextualizer / exporter から使用。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_control_chars(text: str) -> str:
    """改行・タブ以外の制御文字を除去する。"""
    return _CONTROL_CHAR_RE.sub("", text)


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
    line = f"[{ts_display}] {author}: {_strip_control_chars(content)}"
    if has_attachment:
        line += " [添付ファイルあり]"
    return line
