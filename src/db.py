"""Postgres への接続とマルチテナント（guild単位）データ操作。

接続先は環境変数 DATABASE_URL（例: postgresql://oracle:oracle@localhost:5432/oracle）。
パイプライン系の関数は commit しない（呼び出し元がトランザクションを管理する）。
Bot/ワーカーが使うジョブキュー・許可チャンネル系の関数は内部で commit する。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.types.json import Json

from src.models import RawAttachment, RawMessage

_DEFAULT_DSN = "postgresql://oracle:oracle@localhost:5432/oracle"

_DDL = """
CREATE TABLE IF NOT EXISTS guilds (
    guild_id   TEXT PRIMARY KEY,
    guild_name TEXT NOT NULL DEFAULT '',
    joined_at  TEXT,
    left_at    TEXT
);

CREATE TABLE IF NOT EXISTS allowed_channels (
    guild_id     TEXT NOT NULL,
    channel_id   TEXT NOT NULL,
    channel_name TEXT NOT NULL DEFAULT '',
    allowed_by   TEXT,
    allowed_at   TEXT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id             TEXT PRIMARY KEY,
    guild_id       TEXT NOT NULL,
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
CREATE INDEX IF NOT EXISTS idx_messages_guild
    ON messages (guild_id);

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
    guild_id        TEXT NOT NULL,
    last_message_id TEXT NOT NULL,
    crawled_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_index (
    chunk_id      TEXT PRIMARY KEY,
    guild_id      TEXT NOT NULL,
    anchor_msg_id TEXT NOT NULL,
    channel_id    TEXT NOT NULL,
    chunk_text    TEXT NOT NULL,
    context_text  TEXT,
    status        TEXT DEFAULT 'pending',
    indexed_at    TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunk_guild
    ON chunk_index (guild_id);
CREATE INDEX IF NOT EXISTS idx_chunk_no_context
    ON chunk_index (guild_id, channel_id) WHERE context_text IS NULL;

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id            BIGSERIAL PRIMARY KEY,
    guild_id      TEXT NOT NULL,
    kind          TEXT NOT NULL,
    channel_id    TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',
    requested_by  TEXT,
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    error_message TEXT,
    result        TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON ingest_jobs (status, id);

CREATE TABLE IF NOT EXISTS run_log (
    id         BIGSERIAL PRIMARY KEY,
    run_id     TEXT NOT NULL,
    guild_id   TEXT,
    phase      TEXT NOT NULL,
    status     TEXT NOT NULL,
    message    TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_log (
    id                BIGSERIAL PRIMARY KEY,
    guild_id          TEXT NOT NULL,
    user_id           TEXT,                  -- 質問したユーザーID（集計単位の選択肢）
    created_at        TEXT NOT NULL,         -- ISO8601 (UTC)
    kind              TEXT NOT NULL,         -- 'rewrite'|'answer'|'embedding'|'contextualize'
    model             TEXT,
    prompt_tokens     INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens      INTEGER DEFAULT 0,
    cost_usd          NUMERIC DEFAULT 0      -- config の pricing 単価表から算出した推定コスト
);

CREATE INDEX IF NOT EXISTS idx_usage_guild_created
    ON usage_log (guild_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_created
    ON usage_log (created_at);

-- プラン定義（上限・価格のマスタ。ポータルから編集可能・OI-14 C-2）
CREATE TABLE IF NOT EXISTS plan_defs (
    plan_key             TEXT PRIMARY KEY,        -- 'free'|'pro'|'max'（追加可）
    display_name         TEXT NOT NULL,
    channel_limit        INTEGER,                 -- NULL = 無制限
    daily_question_limit INTEGER NOT NULL,        -- 1日あたりの質問上限
    price_jpy            INTEGER NOT NULL DEFAULT 0,
    sort_order           INTEGER NOT NULL DEFAULT 0,
    updated_at           TEXT
);

-- サーバーごとのプラン割当（無い場合は free 扱い・OI-14 C-2）
CREATE TABLE IF NOT EXISTS guild_plans (
    guild_id               TEXT PRIMARY KEY,
    plan_key               TEXT NOT NULL DEFAULT 'free',
    status                 TEXT NOT NULL DEFAULT 'active',  -- active|past_due|canceled
    note                   TEXT,                            -- 手動変更メモ
    updated_at             TEXT,
    stripe_customer_id     TEXT,                            -- 以下 D(Stripe)用に予約・現状NULL
    stripe_subscription_id TEXT,
    current_period_end     TEXT
);

-- 回答1リクエストのデバッグ用トレース（質問・書き換え・ヒットチャンク・回答を1行に保存）。
-- プライバシー上、本番は config の rag.debug_trace=false で無効化する（既定OFF・OI-21）。
CREATE TABLE IF NOT EXISTS chat_trace (
    id                BIGSERIAL PRIMARY KEY,
    guild_id          TEXT NOT NULL,
    user_id           TEXT,                  -- 質問したユーザーID（任意）
    created_at        TEXT NOT NULL,         -- ISO8601 (UTC)
    question          TEXT NOT NULL,         -- ユーザーの元の質問
    rewritten_query   TEXT,                  -- Query Rewriter の出力（検索に使った文）
    answer            TEXT,                  -- 最終回答
    sources           JSONB,                 -- ヒットしたチャンク（channel/anchor/score/chunk_text 等）
    answer_model      TEXT,
    rerank_enabled    BOOLEAN DEFAULT FALSE, -- このリクエストでリランクが効いたか
    prompt_tokens     INTEGER DEFAULT 0,     -- 回答LLMの入力トークン
    completion_tokens INTEGER DEFAULT 0,     -- 回答LLMの出力トークン
    total_tokens      INTEGER DEFAULT 0,     -- 全LLM/embeddingの合計トークン
    cost_usd          NUMERIC DEFAULT 0,     -- 1リクエストの推定総コスト（全段の合計）
    latency_ms        INTEGER                -- answer() 全体の所要時間（ミリ秒）
);

CREATE INDEX IF NOT EXISTS idx_trace_guild_created
    ON chat_trace (guild_id, created_at);
CREATE INDEX IF NOT EXISTS idx_trace_created
    ON chat_trace (created_at);

-- ユーザーが明示的に教えた事実（「覚えておいて」）。Discord過去ログ（chunk_index）とは
-- 別の記憶領域で、回答時に guild 単位で全件をプロンプトへ注入する（少数前提・OI-24）。
CREATE TABLE IF NOT EXISTS memories (
    id                BIGSERIAL PRIMARY KEY,
    guild_id          TEXT NOT NULL,
    subject           TEXT,              -- 誰/何についての事実か（例: かにじる／本人。任意）
    content           TEXT NOT NULL,     -- 覚えておく事実本文（例: ケーキが好き）
    created_by        TEXT,              -- 教えたユーザーID（任意）
    source_channel_id TEXT,              -- 教わったチャンネルID（任意）
    created_at        TEXT NOT NULL      -- ISO8601 (UTC)
);

CREATE INDEX IF NOT EXISTS idx_memories_guild
    ON memories (guild_id);
"""

# ingest_jobs.kind の取りうる値
JOB_INGEST = "ingest"              # クロール→チャンク→文脈付与→インデックス（差分・冪等）
JOB_PURGE_CHANNEL = "purge_channel"  # 1チャンネル分のデータを全削除
JOB_PURGE_GUILD = "purge_guild"      # 1サーバー分のデータを全削除


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(dsn: str | None = None, init: bool = True) -> psycopg.Connection:
    """Postgres に接続する。dsn 未指定なら環境変数 DATABASE_URL を使う。"""
    dsn = dsn or os.environ.get("DATABASE_URL") or _DEFAULT_DSN
    conn = psycopg.connect(dsn)
    if init:
        init_schema(conn)
    return conn


_SEED_PLANS = """
INSERT INTO plan_defs
    (plan_key, display_name, channel_limit, daily_question_limit, price_jpy, sort_order)
VALUES
    ('free', 'Free', 1,    20,     0, 1),
    ('pro',  'Pro',  10,   80,   700, 2),
    ('max',  'MAX',  NULL, 200,  1500, 3)
ON CONFLICT (plan_key) DO NOTHING;
"""


def init_schema(conn: psycopg.Connection) -> None:
    """テーブル・インデックスを作成し、初期プランを seed する（冪等）。"""
    conn.execute(_DDL)
    conn.commit()
    seed_plans(conn)


def seed_plans(conn: psycopg.Connection) -> None:
    """初期プラン（free/pro/max）を投入する（存在すれば何もしない）。

    テストの teardown では全DDL再実行を避けてこれだけ呼ぶ（DDL多重実行による
    ファイルI/O負荷を抑えるため）。"""
    conn.execute(_SEED_PLANS)
    conn.commit()


# ---- guilds / allowed_channels（Bot のスラッシュコマンドが使用・内部で commit）----

def upsert_guild(conn: psycopg.Connection, guild_id: str, guild_name: str) -> None:
    """サーバーを登録する。再参加（left_at あり）の場合は復帰扱いにする。"""
    conn.execute(
        """
        INSERT INTO guilds (guild_id, guild_name, joined_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (guild_id) DO UPDATE SET
            guild_name = EXCLUDED.guild_name,
            left_at    = NULL
        """,
        (guild_id, guild_name, _now()),
    )
    conn.commit()


def mark_guild_left(conn: psycopg.Connection, guild_id: str) -> None:
    conn.execute(
        "UPDATE guilds SET left_at = %s WHERE guild_id = %s", (_now(), guild_id)
    )
    conn.commit()


def allow_channel(
    conn: psycopg.Connection,
    guild_id: str,
    channel_id: str,
    channel_name: str,
    allowed_by: str,
) -> None:
    conn.execute(
        """
        INSERT INTO allowed_channels (guild_id, channel_id, channel_name, allowed_by, allowed_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (guild_id, channel_id) DO UPDATE SET
            channel_name = EXCLUDED.channel_name,
            allowed_by   = EXCLUDED.allowed_by,
            allowed_at   = EXCLUDED.allowed_at
        """,
        (guild_id, channel_id, channel_name, allowed_by, _now()),
    )
    conn.commit()


def deny_channel(conn: psycopg.Connection, guild_id: str, channel_id: str) -> bool:
    """許可を取り消す。行が存在して削除できたら True。"""
    cur = conn.execute(
        "DELETE FROM allowed_channels WHERE guild_id = %s AND channel_id = %s",
        (guild_id, channel_id),
    )
    conn.commit()
    return cur.rowcount > 0


def fetch_allowed_channels(
    conn: psycopg.Connection, guild_id: str
) -> list[tuple[str, str]]:
    """(channel_id, channel_name) のリストを返す。"""
    return conn.execute(
        "SELECT channel_id, channel_name FROM allowed_channels "
        "WHERE guild_id = %s ORDER BY channel_name",
        (guild_id,),
    ).fetchall()


def fetch_mention_map(
    conn: psycopg.Connection, guild_id: str | None = None
) -> dict[str, str]:
    """author_id → 表示名 の対応表を返す（本文中の <@ID> 解決用・OI-18）。

    過去に発言したユーザーが対象。同一IDで表示名が変わっている場合は
    最新（timestamp最大）の表示名を採用する。guild_id 指定でそのサーバーに限定。
    """
    if guild_id is None:
        rows = conn.execute(
            "SELECT DISTINCT ON (author_id) author_id, author_name "
            "FROM messages ORDER BY author_id, timestamp DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT ON (author_id) author_id, author_name "
            "FROM messages WHERE guild_id = %s ORDER BY author_id, timestamp DESC",
            (guild_id,),
        ).fetchall()
    return {author_id: name for author_id, name in rows}


# ---- ingest_jobs ジョブキュー（Bot が enqueue・ワーカーが claim。内部で commit）----

def enqueue_job(
    conn: psycopg.Connection,
    guild_id: str,
    kind: str,
    channel_id: str | None = None,
    requested_by: str | None = None,
) -> int | None:
    """ジョブを投入する。同内容のジョブが queued で待機中なら投入せず None を返す。"""
    dup = conn.execute(
        """
        SELECT id FROM ingest_jobs
        WHERE guild_id = %s AND kind = %s AND status = 'queued'
          AND channel_id IS NOT DISTINCT FROM %s
        LIMIT 1
        """,
        (guild_id, kind, channel_id),
    ).fetchone()
    if dup:
        conn.commit()
        return None
    row = conn.execute(
        """
        INSERT INTO ingest_jobs (guild_id, kind, channel_id, requested_by, created_at)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (guild_id, kind, channel_id, requested_by, _now()),
    ).fetchone()
    conn.commit()
    return row[0]


def claim_next_job(conn: psycopg.Connection) -> dict | None:
    """queued の先頭ジョブを running にして返す（FOR UPDATE SKIP LOCKED で競合安全）。"""
    row = conn.execute(
        """
        UPDATE ingest_jobs SET status = 'running', started_at = %s
        WHERE id = (
            SELECT id FROM ingest_jobs WHERE status = 'queued'
            ORDER BY id LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, guild_id, kind, channel_id, requested_by
        """,
        (_now(),),
    ).fetchone()
    conn.commit()
    if row is None:
        return None
    return {
        "id": row[0],
        "guild_id": row[1],
        "kind": row[2],
        "channel_id": row[3],
        "requested_by": row[4],
    }


def finish_job(
    conn: psycopg.Connection,
    job_id: int,
    ok: bool,
    result: str | None = None,
    error_message: str | None = None,
) -> None:
    conn.execute(
        "UPDATE ingest_jobs SET status = %s, finished_at = %s, result = %s, "
        "error_message = %s WHERE id = %s",
        ("done" if ok else "error", _now(), result, error_message, job_id),
    )
    conn.commit()


def fetch_last_job(conn: psycopg.Connection, guild_id: str) -> dict | None:
    """そのサーバーの最新ジョブを返す（/oracle status 用）。"""
    row = conn.execute(
        """
        SELECT id, kind, status, created_at, finished_at, result, error_message
        FROM ingest_jobs WHERE guild_id = %s ORDER BY id DESC LIMIT 1
        """,
        (guild_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "kind": row[1],
        "status": row[2],
        "created_at": row[3],
        "finished_at": row[4],
        "result": row[5],
        "error_message": row[6],
    }


def guilds_due_for_sync(
    conn: psycopg.Connection, interval_hours: float
) -> list[str]:
    """定期syncの対象 guild_id を返す。

    条件: 在籍中・許可チャンネルあり・実行中/待機中ジョブなし・
    最後の ingest 完了から interval_hours 以上経過（一度も完了していなければ対象）。
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=interval_hours)
    ).isoformat()
    rows = conn.execute(
        """
        SELECT g.guild_id FROM guilds g
        WHERE g.left_at IS NULL
          AND EXISTS (SELECT 1 FROM allowed_channels a WHERE a.guild_id = g.guild_id)
          AND NOT EXISTS (
              SELECT 1 FROM ingest_jobs j
              WHERE j.guild_id = g.guild_id AND j.status IN ('queued', 'running')
          )
          AND COALESCE((
              SELECT MAX(j.finished_at) FROM ingest_jobs j
              WHERE j.guild_id = g.guild_id AND j.kind = 'ingest' AND j.status = 'done'
          ), '') < %s
        ORDER BY g.guild_id
        """,
        (cutoff,),
    ).fetchall()
    return [r[0] for r in rows]


# ---- messages / attachments / crawl_state（crawler が使用）----

def insert_message(conn: psycopg.Connection, msg: RawMessage) -> None:
    conn.execute(
        """
        INSERT INTO messages
            (id, guild_id, channel_id, channel_name, author_id, author_name,
             content, timestamp, has_attachment, is_pinned, reaction_count,
             thread_id, thread_name)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            msg.id, msg.guild_id, msg.channel_id, msg.channel_name,
            msg.author_id, msg.author_name, msg.content,
            msg.timestamp, int(msg.has_attachment), int(msg.is_pinned),
            msg.reaction_count, msg.thread_id, msg.thread_name,
        ),
    )


def insert_attachment(conn: psycopg.Connection, att: RawAttachment) -> None:
    conn.execute(
        """
        INSERT INTO attachments (id, message_id, url, filename, content_type)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (id) DO NOTHING
        """,
        (att.id, att.message_id, att.url, att.filename, att.content_type),
    )


def upsert_crawl_state(
    conn: psycopg.Connection, guild_id: str, channel_id: str, last_message_id: str
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_state (channel_id, guild_id, last_message_id, crawled_at)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT (channel_id) DO UPDATE SET
            guild_id        = EXCLUDED.guild_id,
            last_message_id = EXCLUDED.last_message_id,
            crawled_at      = EXCLUDED.crawled_at
        """,
        (channel_id, guild_id, last_message_id, _now()),
    )


def get_crawl_state(conn: psycopg.Connection, channel_id: str) -> str | None:
    row = conn.execute(
        "SELECT last_message_id FROM crawl_state WHERE channel_id = %s",
        (channel_id,),
    ).fetchone()
    return row[0] if row else None


# ---- chunk_index（chunker / contextualizer / indexer が使用）----

def insert_chunk(
    conn: psycopg.Connection,
    chunk_id: str,
    guild_id: str,
    anchor_msg_id: str,
    channel_id: str,
    chunk_text: str,
) -> None:
    """チャンクを upsert する。本文が変わった場合は context_text を破棄し
    status を 'pending' に戻して、再contextualize・再インデックス対象にする。"""
    conn.execute(
        """
        INSERT INTO chunk_index (chunk_id, guild_id, anchor_msg_id, channel_id, chunk_text)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (chunk_id) DO UPDATE SET
            guild_id      = EXCLUDED.guild_id,
            anchor_msg_id = EXCLUDED.anchor_msg_id,
            channel_id    = EXCLUDED.channel_id,
            chunk_text    = EXCLUDED.chunk_text,
            context_text  = CASE
                WHEN chunk_index.chunk_text    IS DISTINCT FROM EXCLUDED.chunk_text
                  OR chunk_index.anchor_msg_id IS DISTINCT FROM EXCLUDED.anchor_msg_id
                  OR chunk_index.channel_id    IS DISTINCT FROM EXCLUDED.channel_id
                THEN NULL
                ELSE chunk_index.context_text
            END,
            status = CASE
                WHEN chunk_index.chunk_text    IS DISTINCT FROM EXCLUDED.chunk_text
                  OR chunk_index.anchor_msg_id IS DISTINCT FROM EXCLUDED.anchor_msg_id
                  OR chunk_index.channel_id    IS DISTINCT FROM EXCLUDED.channel_id
                THEN 'pending'
                ELSE chunk_index.status
            END
        """,
        (chunk_id, guild_id, anchor_msg_id, channel_id, chunk_text),
    )


def fetch_chunks_by_channel(
    conn: psycopg.Connection, channel_id: str
) -> list[tuple[str, str | None]]:
    """指定 channel_id のチャンクを anchor メッセージの timestamp 昇順で返す。
    戻り値: (chunk_text, context_text) のタプルリスト。
    同時刻メッセージは m.id で安定ソート。
    """
    rows = conn.execute(
        """
        SELECT ci.chunk_text, ci.context_text FROM chunk_index ci
        JOIN messages m ON ci.anchor_msg_id = m.id
        WHERE ci.channel_id = %s
        ORDER BY m.timestamp ASC, m.id ASC
        """,
        (channel_id,),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def update_chunk_context(
    conn: psycopg.Connection, chunk_id: str, context_text: str
) -> None:
    conn.execute(
        "UPDATE chunk_index SET context_text = %s WHERE chunk_id = %s",
        (context_text, chunk_id),
    )


def fetch_chunks_for_context(
    conn: psycopg.Connection, guild_id: str | None = None
) -> list[tuple[str, str, str, str]]:
    """context_text が NULL のチャンクを取得する（guild_id 指定で絞り込み）。
    戻り値: (chunk_id, anchor_msg_id, channel_id, chunk_text) のリスト。
    """
    where = "WHERE context_text IS NULL"
    params: tuple = ()
    if guild_id is not None:
        where += " AND guild_id = %s"
        params = (guild_id,)
    return conn.execute(
        f"""
        SELECT chunk_id, anchor_msg_id, channel_id, chunk_text
        FROM chunk_index
        {where}
        ORDER BY channel_id, chunk_id
        """,
        params,
    ).fetchall()


def fetch_chunks_for_indexing(
    conn: psycopg.Connection,
    guild_id: str | None = None,
    include_indexed: bool = False,
) -> list[tuple[str, str, str, str, str, str | None, str]]:
    """Qdrant 登録対象のチャンクを返す（indexer.py が使用）。
    戻り値: (chunk_id, guild_id, channel_id, channel_name, chunk_text, context_text, anchor_timestamp)
    """
    conds = []
    params: list = []
    if not include_indexed:
        conds.append("ci.status != 'indexed'")
    if guild_id is not None:
        conds.append("ci.guild_id = %s")
        params.append(guild_id)
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    return conn.execute(
        f"""
        SELECT ci.chunk_id, ci.guild_id, ci.channel_id, m.channel_name,
               ci.chunk_text, ci.context_text, m.timestamp
        FROM chunk_index ci
        JOIN messages m ON ci.anchor_msg_id = m.id
        {where}
        ORDER BY ci.channel_id, m.timestamp, m.id
        """,
        params,
    ).fetchall()


def mark_chunks_indexed(conn: psycopg.Connection, chunk_ids: list[str]) -> None:
    """Qdrant 登録済みチャンクの status を 'indexed' に更新する（indexer.py が使用）。"""
    now = _now()
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE chunk_index SET status='indexed', indexed_at=%s, error_message=NULL "
            "WHERE chunk_id=%s",
            [(now, cid) for cid in chunk_ids],
        )


def reset_chunk_index_status(
    conn: psycopg.Connection, guild_id: str | None = None
) -> int:
    """チャンクの status を 'pending' に戻す（indexer.py --clean が使用）。"""
    if guild_id is None:
        cur = conn.execute(
            "UPDATE chunk_index SET status='pending', indexed_at=NULL"
        )
    else:
        cur = conn.execute(
            "UPDATE chunk_index SET status='pending', indexed_at=NULL WHERE guild_id=%s",
            (guild_id,),
        )
    return cur.rowcount


def count_chunks(
    conn: psycopg.Connection,
    status: str | None = None,
    guild_id: str | None = None,
) -> int:
    conds = []
    params: list = []
    if status is not None:
        conds.append("status = %s")
        params.append(status)
    if guild_id is not None:
        conds.append("guild_id = %s")
        params.append(guild_id)
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    row = conn.execute(
        f"SELECT count(*) FROM chunk_index {where}", params
    ).fetchone()
    return row[0]


def count_messages(conn: psycopg.Connection, guild_id: str | None = None) -> int:
    if guild_id is None:
        row = conn.execute("SELECT count(*) FROM messages").fetchone()
    else:
        row = conn.execute(
            "SELECT count(*) FROM messages WHERE guild_id = %s", (guild_id,)
        ).fetchone()
    return row[0]


# ---- データ削除（ワーカーの purge ジョブが使用。Qdrant 側の削除は呼び出し元が行う）----

def purge_channel_data(
    conn: psycopg.Connection, guild_id: str, channel_id: str
) -> dict:
    """1チャンネル分の messages / attachments / chunk_index / crawl_state を削除する。"""
    atts = conn.execute(
        """
        DELETE FROM attachments WHERE message_id IN (
            SELECT id FROM messages WHERE guild_id = %s AND channel_id = %s
        )
        """,
        (guild_id, channel_id),
    ).rowcount
    msgs = conn.execute(
        "DELETE FROM messages WHERE guild_id = %s AND channel_id = %s",
        (guild_id, channel_id),
    ).rowcount
    chunks = conn.execute(
        "DELETE FROM chunk_index WHERE guild_id = %s AND channel_id = %s",
        (guild_id, channel_id),
    ).rowcount
    conn.execute(
        "DELETE FROM crawl_state WHERE guild_id = %s AND channel_id = %s",
        (guild_id, channel_id),
    )
    conn.commit()
    return {"messages": msgs, "attachments": atts, "chunks": chunks}


def purge_guild_data(conn: psycopg.Connection, guild_id: str) -> dict:
    """1サーバー分の全データを削除する。guilds 行は left_at を墓標として残す。

    README の「Bot退出で guild_id のデータは全削除」(#31 / OI-44) を満たすため、
    取り込みデータ（messages/attachments/chunk_index/crawl_state/allowed_channels）に加え、
    ユーザー由来・課金・運用系（memories/chat_trace/usage_log/guild_plans/run_log/ingest_jobs）も削除する。
    特に memories・chat_trace はユーザー発話・明示記憶・ヒットチャンク本文を含むため必須（プライバシー）。
    進行中の purge ジョブ自身（status='running'）だけは finish_job が完了記録できるよう残す。
    """
    atts = conn.execute(
        """
        DELETE FROM attachments WHERE message_id IN (
            SELECT id FROM messages WHERE guild_id = %s
        )
        """,
        (guild_id,),
    ).rowcount
    msgs = conn.execute(
        "DELETE FROM messages WHERE guild_id = %s", (guild_id,)
    ).rowcount
    chunks = conn.execute(
        "DELETE FROM chunk_index WHERE guild_id = %s", (guild_id,)
    ).rowcount
    conn.execute("DELETE FROM crawl_state WHERE guild_id = %s", (guild_id,))
    conn.execute("DELETE FROM allowed_channels WHERE guild_id = %s", (guild_id,))
    # --- #31 (OI-44): プライバシー上残してはいけないユーザー由来・課金・運用系データ ---
    memories = conn.execute(
        "DELETE FROM memories WHERE guild_id = %s", (guild_id,)
    ).rowcount
    traces = conn.execute(
        "DELETE FROM chat_trace WHERE guild_id = %s", (guild_id,)
    ).rowcount
    usage = conn.execute(
        "DELETE FROM usage_log WHERE guild_id = %s", (guild_id,)
    ).rowcount
    conn.execute("DELETE FROM guild_plans WHERE guild_id = %s", (guild_id,))
    conn.execute("DELETE FROM run_log WHERE guild_id = %s", (guild_id,))
    # 進行中の purge ジョブ自身は finish_job が完了記録できるよう残す
    conn.execute(
        "DELETE FROM ingest_jobs WHERE guild_id = %s AND status != 'running'",
        (guild_id,),
    )
    conn.commit()
    return {
        "messages": msgs,
        "attachments": atts,
        "chunks": chunks,
        "memories": memories,
        "traces": traces,
        "usage": usage,
    }


# ---- run_log ----

def log_run(
    conn: psycopg.Connection,
    run_id: str,
    phase: str,
    status: str,
    message: str | None = None,
    guild_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO run_log (run_id, guild_id, phase, status, message, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (run_id, guild_id, phase, status, message, _now()),
    )


# ---- usage_log（LLM/embedding 利用量計測。recorder が commit を管理する）----

def insert_usage(
    conn: psycopg.Connection,
    guild_id: str,
    kind: str,
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
    user_id: str | None = None,
) -> None:
    """LLM/embedding 1回分の利用量を記録する（commit は呼び出し元が行う）。"""
    conn.execute(
        """
        INSERT INTO usage_log
            (guild_id, user_id, created_at, kind, model,
             prompt_tokens, completion_tokens, total_tokens, cost_usd)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (guild_id, user_id, _now(), kind, model,
         prompt_tokens, completion_tokens, total_tokens, cost_usd),
    )


# ---- chat_trace（回答1リクエストのデバッグトレース。recorder が commit を管理する）----

def insert_trace(
    conn: psycopg.Connection,
    guild_id: str,
    question: str,
    rewritten_query: str | None = None,
    answer: str | None = None,
    sources: list[dict] | None = None,
    answer_model: str | None = None,
    rerank_enabled: bool = False,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_ms: int | None = None,
    user_id: str | None = None,
) -> None:
    """回答1リクエスト分のトレースを記録する（commit は呼び出し元が行う）。"""
    conn.execute(
        """
        INSERT INTO chat_trace
            (guild_id, user_id, created_at, question, rewritten_query, answer,
             sources, answer_model, rerank_enabled, prompt_tokens,
             completion_tokens, total_tokens, cost_usd, latency_ms)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (guild_id, user_id, _now(), question, rewritten_query, answer,
         Json(sources) if sources is not None else None,
         answer_model, rerank_enabled, prompt_tokens,
         completion_tokens, total_tokens, cost_usd, latency_ms),
    )


# ---- memories（ユーザーが明示的に教えた事実。「覚えておいて」・OI-24）----

def insert_memory(
    conn: psycopg.Connection,
    guild_id: str,
    content: str,
    subject: str | None = None,
    created_by: str | None = None,
    source_channel_id: str | None = None,
) -> int:
    """教わった事実を1件保存し、その id を返す（書き込み系なので内部で commit）。"""
    row = conn.execute(
        """
        INSERT INTO memories
            (guild_id, subject, content, created_by, source_channel_id, created_at)
        VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (guild_id, subject, content, created_by, source_channel_id, _now()),
    ).fetchone()
    conn.commit()
    return row[0]


def fetch_memories(conn: psycopg.Connection, guild_id: str) -> list[dict]:
    """guild の教わった事実を全件返す（新しい順）。回答時のプロンプト注入に使う。"""
    rows = conn.execute(
        """
        SELECT id, guild_id, subject, content, created_by, source_channel_id, created_at
        FROM memories WHERE guild_id = %s ORDER BY created_at DESC, id DESC
        """,
        (guild_id,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "guild_id": r[1],
            "subject": r[2],
            "content": r[3],
            "created_by": r[4],
            "source_channel_id": r[5],
            "created_at": r[6],
        }
        for r in rows
    ]


def delete_memory(conn: psycopg.Connection, guild_id: str, memory_id: int) -> bool:
    """1件削除する（guild 内のみ）。削除できたら True（書き込み系なので内部で commit）。"""
    cur = conn.execute(
        "DELETE FROM memories WHERE guild_id = %s AND id = %s",
        (guild_id, memory_id),
    )
    conn.commit()
    return cur.rowcount > 0


def count_memories(conn: psycopg.Connection, guild_id: str) -> int:
    """guild の memories 件数を返す。"""
    row = conn.execute(
        "SELECT count(*) FROM memories WHERE guild_id = %s", (guild_id,)
    ).fetchone()
    return row[0]


def _month_start_iso() -> str:
    """今月初日 00:00 UTC の ISO8601 文字列（created_at の文字列比較に使う）。"""
    now = datetime.now(timezone.utc)
    return now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()


def fetch_guilds_overview(conn: psycopg.Connection) -> list[dict]:
    """管理ポータル用: サーバーごとの概況（許可ch数・msg数・chunk数・今月のコスト）。"""
    month_start = _month_start_iso()
    rows = conn.execute(
        """
        SELECT
            g.guild_id, g.guild_name, g.joined_at, g.left_at,
            (SELECT count(*) FROM allowed_channels a WHERE a.guild_id = g.guild_id),
            (SELECT count(*) FROM messages m WHERE m.guild_id = g.guild_id),
            (SELECT count(*) FROM chunk_index c WHERE c.guild_id = g.guild_id),
            COALESCE((
                SELECT sum(u.cost_usd) FROM usage_log u
                WHERE u.guild_id = g.guild_id AND u.created_at >= %s
            ), 0)
        FROM guilds g
        ORDER BY (g.left_at IS NULL) DESC, g.guild_name
        """,
        (month_start,),
    ).fetchall()
    return [
        {
            "guild_id": r[0],
            "guild_name": r[1],
            "joined_at": r[2],
            "left_at": r[3],
            "allowed_count": r[4],
            "message_count": r[5],
            "chunk_count": r[6],
            "cost_usd_this_month": float(r[7]),
        }
        for r in rows
    ]


def fetch_recent_jobs(conn: psycopg.Connection, limit: int = 50) -> list[dict]:
    """管理ポータル用: 最近の取り込みジョブ（処理中・完了・エラー）。"""
    rows = conn.execute(
        """
        SELECT j.id, j.guild_id, g.guild_name, j.kind, j.status,
               j.created_at, j.started_at, j.finished_at, j.result, j.error_message
        FROM ingest_jobs j
        LEFT JOIN guilds g ON g.guild_id = j.guild_id
        ORDER BY j.id DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": r[0], "guild_id": r[1], "guild_name": r[2], "kind": r[3],
            "status": r[4], "created_at": r[5], "started_at": r[6],
            "finished_at": r[7], "result": r[8], "error_message": r[9],
        }
        for r in rows
    ]


def fetch_usage_summary(conn: psycopg.Connection) -> dict:
    """管理ポータル用: 今月の利用量サマリ（合計・種別別・サーバー別）。"""
    month_start = _month_start_iso()
    total = conn.execute(
        "SELECT COALESCE(sum(cost_usd),0), COALESCE(sum(total_tokens),0), count(*) "
        "FROM usage_log WHERE created_at >= %s",
        (month_start,),
    ).fetchone()
    by_kind = conn.execute(
        """
        SELECT kind, COALESCE(sum(cost_usd),0), COALESCE(sum(total_tokens),0), count(*)
        FROM usage_log WHERE created_at >= %s
        GROUP BY kind ORDER BY 2 DESC
        """,
        (month_start,),
    ).fetchall()
    by_guild = conn.execute(
        """
        SELECT u.guild_id, g.guild_name, COALESCE(sum(u.cost_usd),0), count(*)
        FROM usage_log u
        LEFT JOIN guilds g ON g.guild_id = u.guild_id
        WHERE u.created_at >= %s
        GROUP BY u.guild_id, g.guild_name ORDER BY 3 DESC
        """,
        (month_start,),
    ).fetchall()
    return {
        "month_start": month_start,
        "total_cost_usd": float(total[0]),
        "total_tokens": int(total[1]),
        "total_calls": int(total[2]),
        "by_kind": [
            {"kind": r[0], "cost_usd": float(r[1]),
             "tokens": int(r[2]), "calls": int(r[3])}
            for r in by_kind
        ],
        "by_guild": [
            {"guild_id": r[0], "guild_name": r[1],
             "cost_usd": float(r[2]), "calls": int(r[3])}
            for r in by_guild
        ],
    }


# ---- plan_defs / guild_plans（プラン管理・OI-14 C-2。内部で commit する）----

def fetch_plan_defs(conn: psycopg.Connection) -> list[dict]:
    """全プラン定義を sort_order 順で返す（ポータルのプラン編集・quota判定が使用）。"""
    rows = conn.execute(
        "SELECT plan_key, display_name, channel_limit, daily_question_limit, "
        "price_jpy, sort_order FROM plan_defs ORDER BY sort_order, plan_key"
    ).fetchall()
    return [
        {
            "plan_key": r[0], "display_name": r[1], "channel_limit": r[2],
            "daily_question_limit": r[3], "price_jpy": r[4], "sort_order": r[5],
        }
        for r in rows
    ]


def get_plan_def(conn: psycopg.Connection, plan_key: str) -> dict | None:
    row = conn.execute(
        "SELECT plan_key, display_name, channel_limit, daily_question_limit, "
        "price_jpy, sort_order FROM plan_defs WHERE plan_key = %s",
        (plan_key,),
    ).fetchone()
    if row is None:
        return None
    return {
        "plan_key": row[0], "display_name": row[1], "channel_limit": row[2],
        "daily_question_limit": row[3], "price_jpy": row[4], "sort_order": row[5],
    }


def update_plan_def(
    conn: psycopg.Connection,
    plan_key: str,
    display_name: str,
    channel_limit: int | None,
    daily_question_limit: int,
    price_jpy: int,
) -> None:
    """プラン定義の上限・価格を更新する（ポータルから・内部で commit）。"""
    conn.execute(
        "UPDATE plan_defs SET display_name=%s, channel_limit=%s, "
        "daily_question_limit=%s, price_jpy=%s, updated_at=%s WHERE plan_key=%s",
        (display_name, channel_limit, daily_question_limit, price_jpy,
         _now(), plan_key),
    )
    conn.commit()


def get_guild_plan(conn: psycopg.Connection, guild_id: str) -> dict:
    """サーバーの実効プラン（定義の上限を含む）を返す。割当が無ければ free 既定。

    戻り値: {plan_key, display_name, channel_limit, daily_question_limit,
             price_jpy, status}
    """
    row = conn.execute(
        """
        SELECT COALESCE(gp.plan_key, 'free') AS plan_key,
               COALESCE(gp.status, 'active') AS status,
               pd.display_name, pd.channel_limit, pd.daily_question_limit, pd.price_jpy
        FROM (SELECT %s AS guild_id) x
        LEFT JOIN guild_plans gp ON gp.guild_id = x.guild_id
        JOIN plan_defs pd
             ON pd.plan_key = COALESCE(gp.plan_key, 'free')
        """,
        (str(guild_id),),
    ).fetchone()
    if row is None:
        # plan_defs に free が無い等の異常時フォールバック（安全側）
        return {
            "plan_key": "free", "status": "active", "display_name": "Free",
            "channel_limit": 1, "daily_question_limit": 20, "price_jpy": 0,
        }
    return {
        "plan_key": row[0], "status": row[1], "display_name": row[2],
        "channel_limit": row[3], "daily_question_limit": row[4], "price_jpy": row[5],
    }


def set_guild_plan(
    conn: psycopg.Connection,
    guild_id: str,
    plan_key: str,
    note: str | None = None,
    status: str = "active",
) -> None:
    """サーバーのプランを設定する（手動切替・将来はStripe Webhookも使用。内部で commit）。"""
    conn.execute(
        """
        INSERT INTO guild_plans (guild_id, plan_key, status, note, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (guild_id) DO UPDATE SET
            plan_key   = EXCLUDED.plan_key,
            status     = EXCLUDED.status,
            note       = EXCLUDED.note,
            updated_at = EXCLUDED.updated_at
        """,
        (str(guild_id), plan_key, status, note, _now()),
    )
    conn.commit()


def count_questions_since(
    conn: psycopg.Connection, guild_id: str, since_iso: str
) -> int:
    """指定時刻以降の回答（質問）件数を返す（quota判定用・usage_log の answer）。"""
    row = conn.execute(
        "SELECT count(*) FROM usage_log "
        "WHERE guild_id = %s AND kind = 'answer' AND created_at >= %s",
        (str(guild_id), since_iso),
    ).fetchone()
    return row[0]


def count_allowed_channels(conn: psycopg.Connection, guild_id: str) -> int:
    row = conn.execute(
        "SELECT count(*) FROM allowed_channels WHERE guild_id = %s",
        (str(guild_id),),
    ).fetchone()
    return row[0]


def fetch_billing_overview(
    conn: psycopg.Connection, since_iso: str
) -> list[dict]:
    """管理ポータル用: サーバーごとのプラン・本日の消化・ch数・status。"""
    rows = conn.execute(
        """
        SELECT g.guild_id, g.guild_name,
               COALESCE(gp.plan_key, 'free') AS plan_key,
               COALESCE(gp.status, 'active') AS status,
               pd.daily_question_limit, pd.channel_limit,
               (SELECT count(*) FROM allowed_channels a WHERE a.guild_id = g.guild_id),
               (SELECT count(*) FROM usage_log u
                  WHERE u.guild_id = g.guild_id AND u.kind = 'answer'
                    AND u.created_at >= %s)
        FROM guilds g
        LEFT JOIN guild_plans gp ON gp.guild_id = g.guild_id
        JOIN plan_defs pd ON pd.plan_key = COALESCE(gp.plan_key, 'free')
        ORDER BY (g.left_at IS NULL) DESC, g.guild_name
        """,
        (since_iso,),
    ).fetchall()
    return [
        {
            "guild_id": r[0], "guild_name": r[1], "plan_key": r[2], "status": r[3],
            "daily_question_limit": r[4], "channel_limit": r[5],
            "channel_count": r[6], "used_today": r[7],
        }
        for r in rows
    ]
