# アーキテクチャ

## ディレクトリ構成

```
waiwai-oracle/
├── README.md
├── CLAUDE.md
├── .github/
│   └── workflows/
│       └── tests.yml     # CI: PR/push時にpytestを自動実行（Postgresサービスコンテナ）
├── docs/
│   ├── ARCHITECTURE.md   (このファイル)
│   ├── DIAGRAMS.md
│   ├── SCHEMA.md
│   ├── CONFIG.md
│   ├── GCP_MIGRATION.md  # GCP移行runbook（OI-14 E・初心者向け/セキュア）
│   ├── DEVLOG.md
│   └── OPEN_ISSUES.md
├── src/
│   ├── config.py          # config.yml ロード
│   ├── models.py          # dataclass定義（RawMessage, RawAttachment）
│   ├── db.py              # Postgres操作（マルチテナント・ジョブキュー含む）
│   ├── formatter.py       # メッセージ→テキスト変換（共通）
│   ├── collectors/
│   │   ├── base.py        # MessageCollector ABC
│   │   └── text_channel.py # TextChannelCollector実装
│   ├── chunker.py         # チャンク生成ロジック（時間ギャップ方式）
│   ├── contextualizer.py  # LLMによる context_text 付与ロジック（Phase 2.5）
│   ├── exporter.py        # chunk_index → output/*.txt 出力（旧Dify用・任意）
│   ├── embedder.py        # OpenAI Embedding APIラッパー
│   ├── sparse.py          # BM25 sparse 変換（SudachiPy分割・ハイブリッド検索用 #54）
│   ├── vectorstore.py     # Qdrant操作（guild_idマルチテナント前提・purge対応・dense+sparse）
│   ├── indexer.py         # チャンク → embedding → Qdrant 登録（Phase 4）
│   ├── worker.py          # 取り込みワーカー（ingest_jobsキュー処理・定期sync）
│   ├── rag/
│   │   ├── prompts.py     # Query Rewriter・れみちゃん回答プロンプト（Difyから移植・OI-15でリブランド）
│   │   ├── llm.py         # OpenRouterチャットLLMラッパー（Completion=本文+usage を返す）
│   │   └── engine.py      # RAG回答エンジン（書き換え→検索→生成・usage計測・traceデバッグ記録）
│   ├── usage.py           # 利用量コスト算出 + UsageRecorder（usage_log書き込み）
│   ├── trace.py           # 回答デバッグトレース TraceRecorder（chat_trace書き込み・既定OFF・OI-21）
│   ├── quota.py           # プラン上限の判定・JST日次境界・案内文（純ロジック・OI-14 C-2）
│   ├── admin/             # 管理者向けポータル（FastAPI + Jinja2・パスワード認証）
│   │   ├── app.py         # ダッシュボード + /billing（プラン管理）
│   │   ├── auth.py        # 簡易パスワード認証（HMAC署名トークン）
│   │   └── templates/     # base/login/dashboard/error/billing.html
│   ├── api.py             # FastAPI APIサーバ（POST /chat[quota判定], GET /health）
│   └── cli.py             # CLIチャットロジック（/chat クライアント）
├── moimoichan_Discordbot/
│   ├── bot.py             # Discord Bot エントリポイント（/oracleコマンド・guildイベント）
│   ├── store.py           # Bot用DBアクセス層（src/db.py の非同期ラッパー）
│   ├── oracle_client.py   # RAG APIクライアント
│   └── Dockerfile         # リポジトリルートをコンテキストにビルド（src/ を同梱）
├── scripts/
│   ├── check_docs.py      # ドキュメント内 .py 参照の検証（pre-commit hook）
│   ├── install_hooks.sh
│   ├── vm_setup.sh        # GCP VM初期セットアップ（Docker+compose+swap・Phase3）
│   ├── migrate_sqlite_to_pg.py # 旧SQLiteデータのPostgres移行（1回だけ実行）
│   └── migrate_oi_to_issues.py # 旧OI→GitHub Issues移行（1回だけ実行・冪等）
├── dry_run.py             # メッセージ数カウントのみ（取得なし）
├── crawler.py             # Phase 1 エントリポイント（手動実行用）
├── chunker.py             # Phase 2 エントリポイント（手動実行用）
├── contextualizer.py      # Phase 2.5 エントリポイント（手動実行用）
├── exporter.py            # Phase 3 エントリポイント（旧Dify用・任意）
├── indexer.py             # Phase 4 エントリポイント（手動実行用）
├── worker.py              # 取り込みワーカー常駐プロセス（composeのworkerサービス）
├── chat_cli.py            # CLIフロントエンド（動作確認用）
├── tests/                 # pytest（DB系は実Postgres・oracle_test DBを使用）
├── config.yml.example
├── .env.example
├── Dockerfile
├── docker-compose.yml     # postgres / oracle / qdrant / api / admin / worker / bot の7サービス
└── data/                  # Dockerボリュームマウント先（.gitignore）
    ├── messages.db        # 旧SQLite（移行済み・テスト用に保持）
    ├── postgres/          # Postgres永続化データ
    └── qdrant/            # Qdrant永続化データ
```

## データフロー

### 取り込み（自動・マルチテナント）

```
管理者が /oracle allow #channel（または定期sync・/oracle sync）
    ↓ ingest_jobs にジョブ投入（bot.py → store.py → db.py）
worker.py（常駐）がジョブを claim
    ↓
src/worker.py
    1. crawl: 許可チャンネルだけを Discord REST で差分取得 → messages
    2. chunk: 時間ギャップ方式でチャンク生成 → chunk_index
    3. contextualize: LLMで context_text 付与（NULLのチャンクのみ）
    4. index: context_text + chunk_text を embedding → Qdrant 登録
    ↓
ジョブの result に件数を記録（/oracle status で確認できる）
```

- `/oracle deny` → purge_channel ジョブ（Qdrant + Postgres からチャンネルデータ削除）
- Bot退出（on_guild_remove） → purge_guild ジョブ（サーバーの全データ削除）

ルートの `crawler.py` 〜 `indexer.py` は同じ処理を config.yml の guild_id に対して
手動実行するためのスクリプト（デバッグ・再構築用）。

### 回答フロー（オンライン）

フロントエンドは2モード（どちらも同じAPIを呼ぶ薄いクライアント）:
- Discord Bot: `moimoichan_Discordbot/bot.py` → `oracle_client.py`
- CLI（動作確認用）: `chat_cli.py` → `src/cli.py`

```
Discord ユーザー（@メンション） or CLI入力
    ↓ POST /chat {guild_id, query, guild_name}
src/api.py（FastAPI）
    0. プラン上限チェック（src/quota.py）: 本日(JST)の質問数 ≧ プラン日次上限なら
       回答せず案内文を返す（コスト発生なし・OI-14 C-2）。上限内のみ↓へ
    ↓
src/rag/engine.py
    1. Query Rewriter（Gemini 2.5 Flash・現在日時注入）
    2. embedding → Qdrant 検索（guild_id フィルタ必須・top_k=10）
    3. 回答生成（DeepSeek V3.2・れみちゃんプロンプト・guild_name を埋め込み）
    4. 各 LLM/embedding の usage を usage_log に記録（src/usage.py・コスト計測）
    ↓
回答 JSON → Bot が Discord に返信
```

### 管理ポータル（運用閲覧・OI-14 C）

`src/admin/`（FastAPI + Jinja2・別 compose サービス `admin`・既定ポート8001）が
管理者向けダッシュボードを提供する。`ADMIN_PASSWORD` による簡易パスワード認証。

```
管理者ブラウザ → /login（ADMIN_PASSWORD）→ Cookie（HMAC署名トークン）
    ↓ GET /
src/admin/app.py
    ↓ src/db.py の集計関数（読み取り専用）
    - fetch_guilds_overview: サーバー別の許可ch数/msg数/chunk数/今月コスト
    - fetch_recent_jobs:     取り込みジョブの状況（処理中/完了/エラー）
    - fetch_usage_summary:   今月の利用量（合計・種別別・サーバー別）
```

`/billing`（OI-14 C-2）: プラン定義（上限・価格）の編集と、サーバーごとのプラン割当・
本日の消化状況を表示・変更する（`fetch_plan_defs` / `update_plan_def` /
`fetch_billing_overview` / `set_guild_plan`）。プラン切替は現状手動。

## 設計方針

### Collector抽象化
`collectors/base.py` に `MessageCollector` ABCを定義する。
現在は `TextChannelCollector` のみ実装。スレッド対応は将来 `ThreadCollector` を追加するだけでよい構造にしておく。
`collect(conn, run_id, channels=...)` でチャンネルリストを渡すと opt-in 収集になる（ワーカーが使用）。

### マルチテナント
- Postgres の全データ系テーブルと Qdrant の全ポイントが `guild_id` を持ち、検索時は必ず guild_id でフィルタする
- これにより他の Discord サーバーのデータが回答に混ざることを構造的に防ぐ
- 取り込みは opt-in（`allowed_channels` にある チャンネルのみ）。許可取り消し・Bot退出で該当データを削除する

### ジョブキュー（単一ライター）
- 取り込みパイプラインの実行はワーカー1プロセスに直列化（`FOR UPDATE SKIP LOCKED` で claim）
- Bot・手動スクリプトとの同時書き込みは Postgres が調停する（SQLite時代の同時書き込み問題を解消）

### 冪等性
- chunker: chunk_id は anchor_msg_id（チャンク先頭メッセージID）の MD5。upsert により再実行で chunk_text が更新され、本文が変わったチャンクだけ context_text / status がリセットされる。チャンキング方式変更時は `python chunker.py --clean` で削除してから再生成する。
- indexer: chunk_id から決定的に UUID を生成して Qdrant の点IDにするため、再実行は上書きになる。`--clean` で対象guildの点を削除 + status リセット、`--all` で全件再登録。
- worker: ジョブが途中で失敗しても、再実行（次のジョブ投入）で続きから処理される（crawl_state / context_text=NULL / status='pending' が再開点）。
- exporter: 実行のたびに output/ を上書き生成する。状態管理なし。

### 各ファイルの責務上限
1ファイル100行以内を目安とする。超える場合は分割を検討すること。

### 設定と機密情報の分離
- 動作パラメータ → `config.yml`（Gitにコミットしてよい）
- APIキー・トークン類・接続文字列 → `.env`（必ずGitignore）
