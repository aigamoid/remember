from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.models import RawAttachment, RawMessage

_DDL = """
CREATE TABLE IF NOT EXISTS messages (
    id             TEXT PRIMARY KEY,
    channel_id     TEXT NOT NULL,
    channel_name   TEXT NOT NULL,
    author_id      TEXT NOT NULL,
    author_name    TEXT NOT NULL,
    content        TEXT NOT NULL DEFAULT '',
    timestamp      TEXT NOT NULL,
    has_attachment INTEGER DEFAULT 0,
    is_pinned      INTEGER DEFAULT 0,
    reaction_count INTEGER DEFAULT 0,
    thread_id      TEXT,
    thread_name    TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_timestamp
    ON messages (channel_id, timestamp);

CREATE TABLE IF NOT EXISTS attachments (
    id           TEXT PRIMARY KEY,
    message_id   TEXT NOT NULL,
    url          TEXT NOT NULL,
    filename     TEXT NOT NULL,
    content_type TEXT,
    local_path   TEXT,
    description  TEXT,
    described_at TEXT
);

CREATE TABLE IF NOT EXISTS crawl_state (
    channel_id      TEXT PRIMARY KEY,
    last_message_id TEXT NOT NULL,
    crawled_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_index (
    chunk_id      TEXT PRIMARY KEY,
    anchor_msg_id TEXT NOT NULL,
    channel_id    TEXT NOT NULL,
    chunk_text    TEXT NOT NULL,
    dify_doc_id   TEXT,
    status        TEXT DEFAULT 'pending',
    indexed_at    TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS run_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    phase      TEXT NOT NULL,
    status     TEXT NOT NULL,
    message    TEXT,
    created_at TEXT NOT NULL
);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(_DDL)
    conn.commit()
    return conn


def insert_message(conn: sqlite3.Connection, msg: RawMessage) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO messages
            (id, channel_id, channel_name, author_id, author_name,
             content, timestamp, has_attachment, is_pinned, reaction_count,
             thread_id, thread_name)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            msg.id, msg.channel_id, msg.channel_name,
            msg.author_id, msg.author_name, msg.content,
            msg.timestamp, int(msg.has_attachment), int(msg.is_pinned),
            msg.reaction_count, msg.thread_id, msg.thread_name,
        ),
    )


def insert_attachment(conn: sqlite3.Connection, att: RawAttachment) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO attachments (id, message_id, url, filename, content_type)
        VALUES (?,?,?,?,?)
        """,
        (att.id, att.message_id, att.url, att.filename, att.content_type),
    )


def upsert_crawl_state(
    conn: sqlite3.Connection, channel_id: str, last_message_id: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO crawl_state (channel_id, last_message_id, crawled_at)
        VALUES (?,?,?)
        ON CONFLICT(channel_id) DO UPDATE SET
            last_message_id = excluded.last_message_id,
            crawled_at      = excluded.crawled_at
        """,
        (channel_id, last_message_id, now),
    )


def get_crawl_state(conn: sqlite3.Connection, channel_id: str) -> str | None:
    row = conn.execute(
        "SELECT last_message_id FROM crawl_state WHERE channel_id = ?",
        (channel_id,),
    ).fetchone()
    return row[0] if row else None


def insert_chunk(
    conn: sqlite3.Connection,
    chunk_id: str,
    anchor_msg_id: str,
    channel_id: str,
    chunk_text: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO chunk_index
            (chunk_id, anchor_msg_id, channel_id, chunk_text)
        VALUES (?,?,?,?)
        """,
        (chunk_id, anchor_msg_id, channel_id, chunk_text),
    )


def count_chunks(conn: sqlite3.Connection, status: str | None = None) -> int:
    if status is None:
        row = conn.execute("SELECT count(*) FROM chunk_index").fetchone()
    else:
        row = conn.execute(
            "SELECT count(*) FROM chunk_index WHERE status = ?", (status,)
        ).fetchone()
    return row[0]


def log_run(
    conn: sqlite3.Connection,
    run_id: str,
    phase: str,
    status: str,
    message: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO run_log (run_id, phase, status, message, created_at) VALUES (?,?,?,?,?)",
        (run_id, phase, status, message, now),
    )
