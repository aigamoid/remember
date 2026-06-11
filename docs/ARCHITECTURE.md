# アーキテクチャ

## ディレクトリ構成

```
waiwai-oracle/
├── README.md
├── CLAUDE.md
├── docs/
│   ├── ARCHITECTURE.md   (このファイル)
│   ├── DIAGRAMS.md
│   ├── SCHEMA.md
│   ├── CONFIG.md
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
│   ├── vectorstore.py     # Qdrant操作（guild_idマルチテナント前提・purge対応）
│   ├── indexer.py         # チャンク → embedding → Qdrant 登録（Phase 4）
│   ├── worker.py          # 取り込みワーカー（ingest_jobsキュー処理・定期sync）
│   ├── rag/
│   │   ├── prompts.py     # Query Rewriter・わいわいちゃんプロンプト（Difyから移植）
│   │   ├── llm.py         # OpenRouterチャットLLMラッパー
│   │   └── engine.py      # RAG回答エンジン（書き換え→検索→生成）
│   ├── api.py             # FastAPI APIサーバ（POST /chat, GET /health）
│   └── cli.py             # CLIチャットロジック（/chat クライアント）
├── moimoichan_Discordbot/
│   ├── bot.py             # Discord Bot エントリポイント（/oracleコマンド・guildイベント）
│   ├── store.py           # Bot用DBアクセス層（src/db.py の非同期ラッパー）
│   ├── oracle_client.py   # RAG APIクライアント
│   └── Dockerfile         # リポジトリルートをコンテキストにビルド（src/ を同梱）
├── scripts/
│   ├── check_docs.py      # ドキュメント内 .py 参照の検証（pre-commit hook）
│   ├── install_hooks.sh
│   └── migrate_sqlite_to_pg.py # 旧SQLiteデータのPostgres移行（1回だけ実行）
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
├── docker-compose.yml     # postgres / oracle / qdrant / api / worker / bot の6サービス
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
    ↓
src/rag/engine.py
    1. Query Rewriter（Gemini 2.5 Flash・現在日時注入）
    2. embedding → Qdrant 検索（guild_id フィルタ必須・top_k=10）
    3. 回答生成（Kimi K2・わいわいちゃんプロンプト・guild_name を埋め込み）
    ↓
回答 JSON → Bot が Discord に返信
```

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
