# スキーマ定義

## Postgresテーブル

DB: `oracle`（compose の `postgres` サービス・接続先は環境変数 `DATABASE_URL`）。
全テーブルは `src/db.py` の `init_schema()` が作成する（冪等）。
マルチテナント対応のため、データ系テーブルは全て `guild_id`（DiscordサーバーID）を持つ。

### guilds（Bot導入サーバー）

```sql
CREATE TABLE guilds (
    guild_id   TEXT PRIMARY KEY,        -- DiscordサーバーID
    guild_name TEXT NOT NULL DEFAULT '',
    joined_at  TEXT,                    -- Bot参加日時（bot.py の on_guild_join が記録）
    left_at    TEXT                     -- Bot退出日時（NULL=在籍中。再参加でNULLに戻る）
);
```

### allowed_channels（opt-in許可チャンネル）

```sql
CREATE TABLE allowed_channels (
    guild_id     TEXT NOT NULL,
    channel_id   TEXT NOT NULL,
    channel_name TEXT NOT NULL DEFAULT '',
    allowed_by   TEXT,                  -- 許可した管理者のユーザーID
    allowed_at   TEXT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
```

> ワーカーはこのテーブルにあるチャンネル**だけ**をクロールする（opt-in方式）。
> `/oracle allow` で追加、`/oracle deny` で削除（削除時は purge_channel ジョブも投入される）。

### ingest_jobs（取り込みジョブキュー）

```sql
CREATE TABLE ingest_jobs (
    id            BIGSERIAL PRIMARY KEY,
    guild_id      TEXT NOT NULL,
    kind          TEXT NOT NULL,        -- 'ingest' | 'purge_channel' | 'purge_guild'
    channel_id    TEXT,                 -- purge_channel のみ使用
    status        TEXT NOT NULL DEFAULT 'queued', -- 'queued'|'running'|'done'|'error'
    requested_by  TEXT,                 -- 操作したユーザーID / 'scheduler' / 'guild_remove'
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    error_message TEXT,
    result        TEXT                  -- 例: "crawled=120 chunks=15 contexts=15 indexed=15"
);
```

> Bot（bot.py / store.py）が投入し、ワーカー（worker.py）が
> `FOR UPDATE SKIP LOCKED` で1件ずつ取り出して処理する。
> 同一guild・同一kindのジョブが queued にある間は重複投入されない。

### messages（生データ）

```sql
CREATE TABLE messages (
    id            TEXT PRIMARY KEY,        -- Discord message ID
    guild_id      TEXT NOT NULL,           -- マルチテナント分離キー
    channel_id    TEXT NOT NULL,
    channel_name  TEXT NOT NULL,
    author_id     TEXT NOT NULL,
    author_name   TEXT NOT NULL,
    content       TEXT NOT NULL DEFAULT '', -- 添付のみメッセージは空文字
    timestamp     TEXT NOT NULL,            -- ISO8601
    has_attachment INTEGER DEFAULT 0,       -- 0 or 1（attachmentsテーブルと対応）
    is_pinned      INTEGER DEFAULT 0,
    reaction_count INTEGER DEFAULT 0,
    thread_id     TEXT,                     -- スレッド起点でなければNULL
    thread_name   TEXT
);

-- chunkerが頻繁に発行するクエリ用インデックス
CREATE INDEX idx_messages_channel_timestamp ON messages (channel_id, timestamp);
CREATE INDEX idx_messages_guild ON messages (guild_id);
```

### attachments（添付ファイル）

```sql
CREATE TABLE attachments (
    id           TEXT PRIMARY KEY,   -- Discord attachment ID
    message_id   TEXT NOT NULL,      -- messages.id への参照
    url          TEXT NOT NULL,      -- Discord CDN URL（期限切れになっても保持）
    filename     TEXT NOT NULL,
    content_type TEXT,               -- 'image/png', 'video/mp4' など
    local_path   TEXT,               -- ローカルDL時のみ設定（download_attachments: true）
    description  TEXT,               -- 将来: multimodalモデルによるAI生成説明文
    described_at TEXT                -- description生成日時
);
```

### crawl_state（クロール進捗）

```sql
CREATE TABLE crawl_state (
    channel_id      TEXT PRIMARY KEY,
    guild_id        TEXT NOT NULL,
    last_message_id TEXT NOT NULL,    -- ここまで取得済み（差分syncはこの続きから）
    crawled_at      TEXT NOT NULL
);
```

### chunk_index（チャンク管理）

```sql
CREATE TABLE chunk_index (
    chunk_id      TEXT PRIMARY KEY, -- MD5(anchor_msg_id)
    guild_id      TEXT NOT NULL,    -- マルチテナント分離キー
    anchor_msg_id TEXT NOT NULL,
    channel_id    TEXT NOT NULL,    -- exporter.py がチャンネル別出力に使用
    chunk_text    TEXT NOT NULL,    -- タイムスタンプ付き JST テキスト
    context_text  TEXT,             -- LLMが生成した文脈説明（contextualizer.py が付与、NULL=未処理）
    status        TEXT DEFAULT 'pending', -- 'pending' | 'indexed'（indexer.py がQdrant登録済みを記録）
    indexed_at    TEXT,             -- indexer.py がQdrant登録日時を記録
    error_message TEXT
);
```

> **差分sync時の挙動**: `insert_chunk()`（src/db.py）は upsert で、chunk_text が
> 変わった場合のみ `context_text=NULL`・`status='pending'` に戻す。
> これにより新着メッセージで末尾チャンクが伸びたときだけ再contextualize・再インデックスされる。

> **chunk_text のフォーマット：**
> ```
> [2024-05-03 21:13] UserA: 明日の飲み会どこ？
> [2024-05-03 21:14] UserB: 渋谷の居酒屋だよ！
> [2024-05-03 21:15] UserA: わかった、じゃあ参加する [添付ファイルあり]
> ```
> タイムスタンプは `config.yml` の `timezone_offset`（デフォルト 9 = JST）で UTC から変換。

### run_log（実行ログ）

```sql
CREATE TABLE run_log (
    id         BIGSERIAL PRIMARY KEY,
    run_id     TEXT NOT NULL,          -- UUIDなど実行単位の識別子
    guild_id   TEXT,                   -- 対象サーバー（不明な場合はNULL）
    phase      TEXT NOT NULL,          -- 'crawl' | 'chunk' | 'contextualize' | 'index' | 'export'
    status     TEXT NOT NULL,          -- 'success' | 'error' | 'skip'
    message    TEXT,
    created_at TEXT NOT NULL
);
```

### usage_log（LLM/embedding 利用量・コスト計測）

```sql
CREATE TABLE usage_log (
    id                BIGSERIAL PRIMARY KEY,
    guild_id          TEXT NOT NULL,
    user_id           TEXT,                  -- 質問したユーザーID（集計単位の選択肢・任意）
    created_at        TEXT NOT NULL,         -- ISO8601 (UTC)
    kind              TEXT NOT NULL,         -- 'rewrite'|'answer'|'embedding'|'contextualize'
    model             TEXT,
    prompt_tokens     INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens      INTEGER DEFAULT 0,
    cost_usd          NUMERIC DEFAULT 0      -- config.yml の pricing 単価表から算出した推定コスト
);

CREATE INDEX idx_usage_guild_created ON usage_log (guild_id, created_at);
CREATE INDEX idx_usage_created       ON usage_log (created_at);
```

> 回答時に `src/rag/engine.py` が各 LLM/embedding 呼び出しの token 使用量を集め、
> `src/usage.py` の `UsageRecorder` 経由でまとめて記録する（`src/db.py` の `insert_usage`）。
> コストは `config.yml` の `pricing`（USD/100万トークン）から算出。
> 記録失敗は回答処理を止めない（DB障害時でも `/chat` は動く設計）。
> 管理ポータル（`src/admin/`）が `fetch_usage_summary` / `fetch_guilds_overview` で集計表示する。

## Qdrant ペイロード仕様

コレクション: `waiwai_chunks`（config.yml の `qdrant.collection`・全guild共有）
点ID: chunk_id から `uuid5(NAMESPACE_URL, chunk_id)` で決定的に生成（再登録=上書き）
ベクトル: text-embedding-3-small 1536次元（`context_text + "\n\n" + chunk_text` を埋め込み）

```json
{
  "guild_id":         "1072305094718128209",  // 検索時必須フィルタ（マルチテナント分離）
  "chunk_id":         "MD5ハッシュ",
  "channel_id":       "チャンネルID",
  "channel_name":     "チャンネル名",
  "chunk_text":       "タイムスタンプ付き本文",
  "context_text":     "LLM生成の文脈説明 or null",
  "anchor_timestamp": "チャンク先頭メッセージのISO8601（UTC）"
}
```

`/oracle deny`・Bot退出時は guild_id（+ channel_id）フィルタで点を削除する
（`src/vectorstore.py` の `delete_by_channel` / `delete_by_guild`）。

## 旧SQLiteからの移行

単一guild時代の `data/messages.db`（SQLite）は `scripts/migrate_sqlite_to_pg.py` で
guild_id を付与しながら Postgres へ移行済み（2026-06-11）。
status='indexed' を保持して移行するため、再embedding は発生しない。
旧 `upload_state` テーブル（Dify用）と `chunk_index.dify_doc_id` 列は廃止した。
