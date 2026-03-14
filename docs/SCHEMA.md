# スキーマ定義

## SQLiteテーブル

### messages（生データ）

```sql
CREATE TABLE messages (
    id            TEXT PRIMARY KEY,   -- Discord message ID
    channel_id    TEXT NOT NULL,
    channel_name  TEXT NOT NULL,
    author_id     TEXT NOT NULL,
    author_name   TEXT NOT NULL,
    content       TEXT NOT NULL,
    timestamp     TEXT NOT NULL,      -- ISO8601
    has_attachment INTEGER DEFAULT 0, -- 0 or 1
    is_pinned      INTEGER DEFAULT 0,
    reaction_count INTEGER DEFAULT 0,
    thread_id     TEXT,               -- スレッド起点でなければNULL
    thread_name   TEXT
);
```

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
    chunk_id         TEXT PRIMARY KEY, -- MD5(anchor_msg_id + window_before + window_after)
    anchor_msg_id    TEXT NOT NULL,
    dify_doc_id      TEXT,             -- Dify側のドキュメントID（upload後に設定）
    status           TEXT DEFAULT 'pending', -- 'pending' | 'indexed' | 'error'
    indexed_at       TEXT,
    error_message    TEXT
);
```

### run_log（実行ログ）

```sql
CREATE TABLE run_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,          -- UUIDなど実行単位の識別子
    phase      TEXT NOT NULL,          -- 'crawl' | 'chunk' | 'upload' | 'dry_run'
    status     TEXT NOT NULL,          -- 'success' | 'error' | 'skip'
    message    TEXT,
    created_at TEXT NOT NULL
);
```

---

## チャンクのメタデータ仕様

Dify Knowledge APIに渡すメタデータ。チャンク1件ごとに付与する。

```python
metadata = {
    # チャンネル情報
    "channel_id":        "111222333",
    "channel_name":      "general",

    # 時刻情報
    "timestamp_start":   "2024-01-15T22:13:00",
    "timestamp_end":     "2024-01-15T22:18:00",

    # チャンク構造
    "anchor_msg_id":     "999888777",
    "chunk_id":          "abc123...",

    # 発言者
    "authors":           ["UserA", "UserB"],  # チャンク内の発言者リスト

    # コンテンツ属性
    "has_attachment":    False,
    "is_pinned":         False,
    "reaction_count":    3,          # チャンク内の最大リアクション数

    # スレッド情報（将来用）
    "is_thread":         False,
    "thread_name":       None,
}
```

### メタデータ設計の背景（想定クエリとの対応）

| 想定クエリ | 使用メタデータ |
|---|---|
| 「UserAが言ってたXXXは？」 | `authors` |
| 「#general での話題は？」 | `channel_name` |
| 「去年の夏ごろの話」 | `timestamp_start` |
| 「画像が貼られた文脈」 | `has_attachment` |
| 「ピン留めの内容」 | `is_pinned` |
| 「盛り上がった発言」 | `reaction_count` |
| 「スレッドで深掘りされた話」 | `is_thread`, `thread_name` |
| サーバー内スラング・固有名詞 | メタデータ不要（セマンティック検索） |
