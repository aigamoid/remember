"""メッセージ→テキスト変換の共通関数。chunker / contextualizer / exporter から使用。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Discordのユーザーメンション。<@123> と <@!123>（ニックネーム表記）の両方。
_MENTION_RE = re.compile(r"<@!?(\d+)>")


def _strip_control_chars(text: str) -> str:
    """改行・タブ以外の制御文字を除去する。"""
    return _CONTROL_CHAR_RE.sub("", text)


def resolve_mentions(text: str, mention_map: dict[str, str]) -> str:
    """本文中の <@ID> / <@!ID> を @表示名 に置換する（OI-18）。

    mention_map（author_id → 表示名）に無いIDは元の表記のまま残す。
    """
    if not mention_map:
        return text

    def _sub(m: re.Match) -> str:
        name = mention_map.get(m.group(1))
        return f"@{name}" if name else m.group(0)

    return _MENTION_RE.sub(_sub, text)


def format_message_line(
    author: str,
    content: str,
    timestamp: str,
    has_attachment: bool,
    tz_offset: int = 9,
    mention_map: dict[str, str] | None = None,
) -> str:
    """1メッセージを '[YYYY-MM-DD HH:MM] author: content' 形式に変換する。

    mention_map を渡すと本文中の <@ID> を @表示名 に解決する。
    """
    tz = timezone(timedelta(hours=tz_offset))
    dt = datetime.fromisoformat(timestamp).astimezone(tz)
    ts_display = dt.strftime("%Y-%m-%d %H:%M")
    if mention_map:
        content = resolve_mentions(content, mention_map)
    line = f"[{ts_display}] {author}: {_strip_control_chars(content)}"
    if has_attachment:
        line += " [添付ファイルあり]"
    return line
