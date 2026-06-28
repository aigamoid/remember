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

### plan_defs（プラン定義マスタ・OI-14 C-2）

```sql
CREATE TABLE plan_defs (
    plan_key             TEXT PRIMARY KEY,        -- 'free'|'pro'|'max'（追加可）
    display_name         TEXT NOT NULL,
    channel_limit        INTEGER,                 -- NULL = 無制限
    daily_question_limit INTEGER NOT NULL,        -- 1日あたりの質問上限
    price_jpy            INTEGER NOT NULL DEFAULT 0,
    sort_order           INTEGER NOT NULL DEFAULT 0,
    updated_at           TEXT
);
```

> 上限・価格の**マスタ**。`init_schema` が初期3プラン（free:1ch/20問, pro:10ch/80問/¥700,
> max:無制限/200問/¥1500）を seed する（`seed_plans`・`ON CONFLICT DO NOTHING` ＝既存値は壊さない）。
> 値は**管理ポータル `/billing` から編集可能**（コード/再デプロイ不要）。`src/db.py` の
> `fetch_plan_defs` / `get_plan_def` / `update_plan_def` が読み書きする。

### guild_plans（サーバーごとのプラン割当・OI-14 C-2）

```sql
CREATE TABLE guild_plans (
    guild_id               TEXT PRIMARY KEY,
    plan_key               TEXT NOT NULL DEFAULT 'free',
    status                 TEXT NOT NULL DEFAULT 'active',  -- active|past_due|canceled
    note                   TEXT,                            -- 手動変更メモ
    updated_at             TEXT,
    stripe_customer_id     TEXT,   -- 以下 OI-14 D(Stripe)用に予約・現状NULL
    stripe_subscription_id TEXT,
    current_period_end     TEXT
);
```

> 行が無いサーバーは **free 扱い**（`get_guild_plan` が plan_defs と結合して実効上限を返す）。
> プランは現状**手動切替**（ポータル `/billing` の `set_guild_plan`）。OI-14 D で Stripe Webhook が
> `stripe_*` / `status` を自動更新する想定。
> **上限の強制**: 質問の日次上限は `src/api.py` の `/chat` 入口で（`src/quota.py` 判定・超過時は
> 回答せず案内＝コスト0）、チャンネル数上限は Bot の `/oracle allow` で（`store.py`）。
> 日次集計は `count_questions_since`（JST 0時境界は `quota.jst_day_start_utc_iso`）。

### chat_trace（回答デバッグトレース・OI-21）

```sql
CREATE TABLE chat_trace (
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
    hybrid_enabled    BOOLEAN DEFAULT FALSE, -- このリクエストでハイブリッド検索が効いたか（#54/#58）
    prompt_tokens     INTEGER DEFAULT 0,     -- 回答LLMの入力トークン
    completion_tokens INTEGER DEFAULT 0,     -- 回答LLMの出力トークン
    total_tokens      INTEGER DEFAULT 0,     -- 全LLM/embeddingの合計トークン
    cost_usd          NUMERIC DEFAULT 0,     -- 1リクエストの推定総コスト（全段の合計）
    latency_ms        INTEGER                -- answer() 全体の所要時間（ミリ秒）
);

CREATE INDEX idx_trace_guild_created ON chat_trace (guild_id, created_at);
CREATE INDEX idx_trace_created       ON chat_trace (created_at);
```

> **デバッグ/開発用**。1回の `/chat` の中身（質問・書き換え後クエリ・ヒットチャンク本文・回答・
> トークン/コスト/レイテンシ）を1行で残す。検索品質やプロンプトの A/B、回答が外した原因の追跡に使う。
> `src/rag/engine.py` の `answer()` が `src/trace.py` の `TraceRecorder` 経由で記録する
> （`src/db.py` の `insert_trace`）。usage_log 同様、記録失敗は回答を止めない。
> **既定オフ**。`config.yml` の `rag.debug_trace: true` のときだけ記録する（質問・回答本文を
> 保存するため、本番ではプライバシー上 false 運用が前提）。

### memories（明示メモリ「覚えておいて」・OI-24）

```sql
CREATE TABLE memories (
    id                BIGSERIAL PRIMARY KEY,
    guild_id          TEXT NOT NULL,
    subject           TEXT,              -- 誰/何についての事実か（例: かにじる／本人。任意）
    content           TEXT NOT NULL,     -- 覚えておく事実本文（例: ケーキが好き）
    created_by        TEXT,              -- 教えたユーザーID（任意）
    source_channel_id TEXT,              -- 教わったチャンネルID（任意）
    created_at        TEXT NOT NULL      -- ISO8601 (UTC)
);

CREATE INDEX idx_memories_guild ON memories (guild_id);
```

> ユーザーが「覚えておいて」と**明示的に教えた事実**を保持する、Discord過去ログ（`chunk_index`/
> Qdrant）とは**別の記憶領域**（OI-24）。回答時に guild 単位で**全件**をプロンプトへ注入する
> （少数前提＝ベクトル検索を使わない。件数が増えたら別Qdrantコレクション化を検討）。
> `src/db.py` の `insert_memory` / `fetch_memories` / `delete_memory` / `count_memories` が
> 読み書きし、`src/memory.py` の `MemoryProvider` 経由で `src/rag/engine.py` の `answer()` が
> プロンプトへ注入する。**既定オフ**（`config.yml` の `rag.memory_enabled: true` のときだけ注入）。
> 書き込みUI（「覚えておいて」検知）は A/B で効果確認後に実装予定。

### personas（真似っこモードの人格カード・#49）

```sql
CREATE TABLE personas (
    guild_id     TEXT NOT NULL,
    author_id    TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    card         JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {nicknames,personality,likes,speech_style,catchphrases,confidence}
    sample_count INTEGER NOT NULL DEFAULT 0,           -- カード生成に使った発言数
    consent      TEXT NOT NULL DEFAULT 'unknown',      -- 'unknown'|'optin'|'optout'（本人 opt-out で除外）
    created_by   TEXT,                                 -- 真似を開始した実行者
    created_at   TEXT NOT NULL,
    updated_at   TEXT,
    PRIMARY KEY (guild_id, author_id)
);
CREATE INDEX idx_personas_guild ON personas (guild_id);
```

> 対象メンバーの過去発言（`messages`）から生成した「口調・性格カード」を保持する（#49）。
> **guild+author 単位＝サーバー全体でのその人の傾向**で、guild 資産として保持する。
> `purge_channel`（`/oracle deny`）では**消さない**。`purge_guild`・Bot退出でのみ削除する。
> `src/db.py` の `upsert_persona_card`/`fetch_persona_card`/`set_persona_consent`/
> `get_persona_consent`/`delete_persona_card` が読み書きし、生成は `src/rag/engine.py` の
> `build_persona_card()`（センシティブ属性は `prompts.sanitize_persona_card` で保存前に除去）。
> `consent='optout'` の人は `/mimic/start` で開始を拒否する（本人保護）。

### mimic_state（真似っこモードの現在状態・#49）

```sql
CREATE TABLE mimic_state (
    guild_id   TEXT NOT NULL,
    channel_id TEXT NOT NULL,    -- scope=channel 固定（宣言した ch だけ真似が効く）
    author_id  TEXT NOT NULL,    -- いま真似中の対象
    started_by TEXT,
    started_at TEXT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
CREATE INDEX idx_mimic_state_guild ON mimic_state (guild_id);
```

> 「いまどの channel で誰を真似中か」を保持する（#49）。**1 channel = 1 対象**（upsert で上書き）。
> 回答時に `src/mimic.py` の `MimicProvider`（`get_active_mimic`→`fetch_persona_card`）が解決し、
> `engine.answer()` が人格カードを `{mimic_section}` に注入する。**guild への fallback はしない**
> （意図せぬサーバー全体適用を防ぐ）。`/oracle mimic_off` で解除（`clear_mimic_state`）。
> `purge_channel` はその channel の行だけ削除、`purge_guild`・退出は guild 単位で全削除。
> **既定オフ**（`config.yml` の `rag.mimic_enabled: true` のときだけ機能する）。
> あわせて `messages (guild_id, author_id, timestamp DESC)` のインデックスを追加（カード生成の高速化）。

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
