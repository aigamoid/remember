# スキーマ定義

## SQLiteテーブル

### messages（生データ）

```sql
CREATE TABLE messages (
    id            TEXT PRIMARY KEY,        -- Discord message ID
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
CREATE INDEX IF NOT EXISTS idx_messages_channel_timestamp
    ON messages (channel_id, timestamp);
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

> **config.yml での制御：**
> ```yaml
> crawl:
>   download_attachments: false        # true にするとクロール時にローカルDL
>   attachment_dir: "data/attachments" # DL先（download_attachments: true 時のみ使用）
> ```
>
> `local_path` が NULL の場合、将来の `describer.py` は `url` からのDLを試みる（期限切れ時は skip）。

---

### crawl_state（クロール進捗）

```sql
CREATE TABLE crawl_state (
    channel_id      TEXT PRIMARY KEY,
    last_message_id TEXT NOT NULL,    -- ここまで取得済み
    crawled_at      TEXT NOT NULL
);
```

### chunk_index（チャンク管理）

```sql
CREATE TABLE chunk_index (
    chunk_id      TEXT PRIMARY KEY, -- MD5(anchor_msg_id)
    anchor_msg_id TEXT NOT NULL,
    channel_id    TEXT NOT NULL,    -- exporter.py がチャンネル別出力に使用
    chunk_text    TEXT NOT NULL,    -- タイムスタンプ付き JST テキスト（exporter.py がファイルに出力）
    context_text  TEXT,             -- LLMが生成した文脈説明（contextualizer.py が付与、NULL=未処理）
    dify_doc_id   TEXT,             -- 旧Dify用（廃止済み・未使用）
    status        TEXT DEFAULT 'pending', -- 'pending' | 'indexed'（indexer.py がQdrant登録済みを記録）
    indexed_at    TEXT,             -- indexer.py がQdrant登録日時を記録
    error_message TEXT
);
```

> **chunk_text のフォーマット：**
> ```
> [2024-05-03 21:13] UserA: 明日の飲み会どこ？
> [2024-05-03 21:14] UserB: 渋谷の居酒屋だよ！
> [2024-05-03 21:15] UserA: わかった、じゃあ参加する [添付ファイルあり]
> ```
> タイムスタンプは `config.yml` の `timezone_offset`（デフォルト 9 = JST）で UTC から変換。

> **context_text のフォーマット：**
> LLMが生成した1〜2文の文脈説明。exporter.py は chunk_text の前に `[CONTEXT]\n...\n[CHUNK]\n` 形式で付加して出力する。

## Qdrant ペイロード仕様

コレクション: `waiwai_chunks`（config.yml の `qdrant.collection`）
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

### upload_state（チャンネル別アップロード状態・旧Dify用）

```sql
CREATE TABLE upload_state (
    channel_id    TEXT PRIMARY KEY,
    channel_name  TEXT NOT NULL,
    dataset_id    TEXT,             -- Dify側のデータセットID
    document_id   TEXT,             -- Dify側のドキュメントID
    status        TEXT DEFAULT 'pending', -- 'pending' | 'indexed' | 'error'
    error_message TEXT,
    indexed_at    TEXT
);
```

### run_log（実行ログ）

```sql
CREATE TABLE run_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,          -- UUIDなど実行単位の識別子
    phase      TEXT NOT NULL,          -- 'crawl' | 'chunk' | 'contextualize' | 'export'
    status     TEXT NOT NULL,          -- 'success' | 'error' | 'skip'
    message    TEXT,
    created_at TEXT NOT NULL
);
```
