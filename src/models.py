from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RawMessage:
    id: str
    guild_id: str
    channel_id: str
    channel_name: str
    author_id: str
    author_name: str
    content: str            # 添付のみメッセージは空文字
    timestamp: str          # ISO8601 UTC
    has_attachment: bool
    is_pinned: bool
    reaction_count: int
    thread_id: str | None
    thread_name: str | None
    is_bot: bool = False    # #68: Bot/Webhook 発言。取り込み（チャンク化・文脈付与）から除外する


@dataclass
class RawAttachment:
    id: str
    message_id: str
    url: str
    filename: str
    content_type: str | None  # 'image/png', 'video/mp4' など
