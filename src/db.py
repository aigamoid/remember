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
    context_text  TEXT,
    dify_doc_id   TEXT,
    status        TEXT DEFAULT 'pending',
    indexed_at    TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS upload_state (
    channel_id    TEXT PRIMARY KEY,
    channel_name  TEXT NOT NULL,
    dataset_id    TEXT,
    document_id   TEXT,
    status        TEXT DEFAULT 'pending',
    error_message TEXT,
    indexed_at    TEXT
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
    add_context_text_column(conn)
    conn.commit()
    return conn


def add_context_text_column(conn: sqlite3.Connection) -> None:
    """context_text カラムが無い場合のみ ALTER TABLE で追加し、部分インデックスを作成する（冪等）。"""
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(chunk_index)").fetchall()
    }
    if "context_text" not in existing:
        conn.execute("ALTER TABLE chunk_index ADD COLUMN context_text TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chunk_no_context
            ON chunk_index(channel_id, chunk_id) WHERE context_text IS NULL
        """
    )


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
        INSERT INTO chunk_index (chunk_id, anchor_msg_id, channel_id, chunk_text)
        VALUES (?,?,?,?)
        ON CONFLICT(chunk_id) DO UPDATE SET
            anchor_msg_id = excluded.anchor_msg_id,
            channel_id    = excluded.channel_id,
            chunk_text    = excluded.chunk_text,
            context_text  = CASE
                WHEN chunk_index.chunk_text    IS NOT excluded.chunk_text
                  OR chunk_index.anchor_msg_id IS NOT excluded.anchor_msg_id
                  OR chunk_index.channel_id    IS NOT excluded.channel_id
                THEN NULL
                ELSE chunk_index.context_text
            END
        """,
        (chunk_id, anchor_msg_id, channel_id, chunk_text),
    )


def fetch_chunks_by_channel(
    conn: sqlite3.Connection, channel_id: str
) -> list[tuple[str, str | None]]:
    """指定 channel_id のチャンクを anchor メッセージの timestamp 昇順で返す。
    戻り値: (chunk_text, context_text) のタプルリスト。
    同時刻メッセージは m.id で安定ソート。
    """
    rows = conn.execute(
        """
        SELECT ci.chunk_text, ci.context_text FROM chunk_index ci
        JOIN messages m ON ci.anchor_msg_id = m.id
        WHERE ci.channel_id = ?
        ORDER BY m.timestamp ASC, m.id ASC
        """,
        (channel_id,),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def update_chunk_context(
    conn: sqlite3.Connection, chunk_id: str, context_text: str
) -> None:
    """context_text を chunk_id で更新する。"""
    conn.execute(
        "UPDATE chunk_index SET context_text = ? WHERE chunk_id = ?",
        (context_text, chunk_id),
    )


def fetch_chunks_for_context(
    conn: sqlite3.Connection,
) -> list[tuple[str, str, str, str]]:
    """context_text が NULL のチャンクを全件取得する。
    戻り値: (chunk_id, anchor_msg_id, channel_id, chunk_text) のリスト。
    """
    return conn.execute(
        """
        SELECT chunk_id, anchor_msg_id, channel_id, chunk_text
        FROM chunk_index
        WHERE context_text IS NULL
        ORDER BY channel_id, chunk_id
        """
    ).fetchall()


def fetch_chunks_for_indexing(
    conn: sqlite3.Connection, include_indexed: bool = False
) -> list[tuple[str, str, str, str, str | None, str]]:
    """Qdrant 登録対象のチャンクを返す（indexer.py が使用）。
    戻り値: (chunk_id, channel_id, channel_name, chunk_text, context_text, anchor_timestamp)
    """
    where = "" if include_indexed else "WHERE ci.status != 'indexed'"
    return conn.execute(
        f"""
        SELECT ci.chunk_id, ci.channel_id, m.channel_name,
               ci.chunk_text, ci.context_text, m.timestamp
        FROM chunk_index ci
        JOIN messages m ON ci.anchor_msg_id = m.id
        {where}
        ORDER BY ci.channel_id, m.timestamp, m.id
        """
    ).fetchall()


def mark_chunks_indexed(conn: sqlite3.Connection, chunk_ids: list[str]) -> None:
    """Qdrant 登録済みチャンクの status を 'indexed' に更新する（indexer.py が使用）。"""
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "UPDATE chunk_index SET status='indexed', indexed_at=?, error_message=NULL "
        "WHERE chunk_id=?",
        [(now, cid) for cid in chunk_ids],
    )


def reset_chunk_index_status(conn: sqlite3.Connection) -> int:
    """全チャンクの status を 'pending' に戻す（indexer.py --clean が使用）。"""
    cur = conn.execute(
        "UPDATE chunk_index SET status='pending', indexed_at=NULL"
    )
    return cur.rowcount


def count_chunks(conn: sqlite3.Connection, status: str | None = None) -> int:
    if status is None:
        row = conn.execute("SELECT count(*) FROM chunk_index").fetchone()
    else:
        row = conn.execute(
            "SELECT count(*) FROM chunk_index WHERE status = ?", (status,)
        ).fetchone()
    return row[0]


def init_upload_state(conn: sqlite3.Connection) -> int:
    """messages テーブルのチャンネル一覧から未登録分を upload_state に追加する。"""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO upload_state (channel_id, channel_name)
        SELECT DISTINCT channel_id, channel_name FROM messages
        """
    )
    return cur.rowcount


def fetch_pending_channels(conn: sqlite3.Connection) -> list[tuple[str, str, str | None]]:
    """pending チャンネルを返す。(channel_id, channel_name, dataset_id)"""
    return conn.execute(
        "SELECT channel_id, channel_name, dataset_id FROM upload_state WHERE status = 'pending'"
    ).fetchall()


def mark_channel_indexed(
    conn: sqlite3.Connection, channel_id: str, dataset_id: str, document_id: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE upload_state SET status='indexed', dataset_id=?, document_id=?, indexed_at=? WHERE channel_id=?",
        (dataset_id, document_id, now, channel_id),
    )


def mark_channel_error(
    conn: sqlite3.Connection, channel_id: str, error_msg: str,
    dataset_id: str | None = None,
    document_id: str | None = None,
) -> None:
    if dataset_id:
        conn.execute(
            "UPDATE upload_state SET status='error', error_message=?, dataset_id=?, document_id=? WHERE channel_id=?",
            (error_msg, dataset_id, document_id, channel_id),
        )
    else:
        conn.execute(
            "UPDATE upload_state SET status='error', error_message=? WHERE channel_id=?",
            (error_msg, channel_id),
        )


def reset_upload_errors(conn: sqlite3.Connection) -> int:
    """error → pending に戻す。dataset_id は保持。"""
    cur = conn.execute(
        "UPDATE upload_state SET status='pending', error_message=NULL WHERE status='error'"
    )
    return cur.rowcount


def fetch_datasets_to_clean(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """dataset_id が記録されている全チャンネルを返す。(channel_id, channel_name, dataset_id)"""
    return conn.execute(
        "SELECT channel_id, channel_name, dataset_id FROM upload_state WHERE dataset_id IS NOT NULL"
    ).fetchall()


def reset_all_upload_state(conn: sqlite3.Connection) -> int:
    """全チャンネルを pending に戻し、dataset_id/document_id をクリアする。"""
    cur = conn.execute(
        "UPDATE upload_state SET status='pending', dataset_id=NULL, document_id=NULL, "
        "error_message=NULL, indexed_at=NULL"
    )
    return cur.rowcount


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
