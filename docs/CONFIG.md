# 設定ファイル仕様

## config.yml

```yaml
guild_id: 123456789          # 手動スクリプト（crawler.py等）の対象サーバーID
                             # 通常運用はワーカーがジョブのguild_idで動くため未使用

crawl:
  exclude_channels:          # 除外チャンネル名リスト（手動クロール時のみ有効）
    - bot-log
    - spam
  exclude_channel_ids:       # IDでの除外（名前変更に強い）
    - 987654321
  download_attachments: false        # true にするとクロール時に添付ファイルをローカルDL
  attachment_dir: "data/attachments" # DL先（download_attachments: true 時のみ使用）

chunk:
  time_gap_minutes: 60       # N分以上の間隔があればチャンク境界（会話スレッド単位）
  max_chunk_messages: 30     # 1チャンクに含める最大メッセージ数
  min_content_length: 10     # これ未満の文字数メッセージはスキップ
  short_reply_max_chars: 10  # これ以下の短文は直前チャンクに吸収（疑似reply_to）
  timezone_offset: 9         # タイムスタンプ表示のUTCオフセット（JST=9）

openai:
  api_key: ""              # 空なら環境変数 OPENAI_API_KEY を使用
  base_url: ""             # 空=OpenAIデフォルト / OpenRouter: https://openrouter.ai/api/v1

contextualizer:
  model: "gpt-4.1-nano"   # context_text 生成モデル
  preceding_messages: 10  # 直前のメッセージ参照数
  max_retries: 3          # API エラー時のリトライ回数
  retry_delay: 1.0        # リトライ間隔（秒）
  concurrency: 10         # 同時実行数（--concurrency 引数で上書き可）

qdrant:
  url: "http://localhost:6333"   # Qdrant接続先。コンテナ内では環境変数 QDRANT_URL が優先
  collection: "waiwai_chunks"    # コレクション名（全guild共有・payloadのguild_idで分離）

embedding:
  model: "text-embedding-3-small"  # OpenAI embeddingモデル（indexer.py / RAG検索で使用）
  dimensions: 1536                 # ベクトル次元数（コレクション作成時に固定される）
  batch_size: 100                  # 1回のembedding APIに渡すチャンク数

rag:
  rewriter_model: "google/gemini-2.5-flash"   # Query Rewriter（OpenRouter経由）
  answer_model: "moonshotai/kimi-k2-0905"     # 回答生成LLM（OpenRouter経由）
  top_k: 10                                   # 回答に渡すチャンク数（リランク有効時はリランク後の件数）
  history_max_turns: 5                        # マルチターン会話で渡す直近やり取りの上限ペア数（OI-10）
                                              # 0で無効（1問1答に戻す）。大きいほど文脈を保てるがprompt tokenが増える
  history_max_chars: 4000                      # 履歴の合計文字数バジェット（回答LLM向け・超過分は古い方から落とす）
                                              # 長い回答が積み重なってtokenが膨張するのを防ぐ安全弁（0で無制限）
  rewriter_history_max_turns: 2               # Query Rewriterに渡す履歴のペア数（指示語解決には少数で十分）
  rewriter_history_max_chars: 1000            # 同・文字数バジェット。履歴はrewriterにも乗るため別途絞ってtoken二重計上を抑制
  guild_name: "わいわい"                       # プロンプト用サーバー名のデフォルト
                                              # （Bot経由のリクエストでは実サーバー名が優先される）
  debug_trace: false                          # OI-21: 質問/ヒットチャンク/回答を chat_trace に保存（デバッグ用）
                                              # 既定OFF。質問・回答本文を残すため本番はプライバシー上 false 運用が前提
  search_gate: true                           # OI-23: 検索ゲート（既定ON）
                                              # 挨拶・雑談・ゲーム・一般質問など過去ログ参照が不要な入力を
                                              # Query Rewriter が [NO_SEARCH] と判定したら、埋め込み・検索・
                                              # リランクをスキップして素の雑談として回答する（コスト/レイテンシ削減）。
                                              # 誤スキップを避けるため判定は「迷ったら検索」に倒している。
                                              # false にすると常に検索する（従来動作）。
  reranker:                                   # OI-9: 検索結果のリランキング（任意・既定オフ）
    enabled: false                            # true で有効化（要 .env の JINA_API_KEY）
    provider: "jina"                          # 現状 jina のみ対応
    model: "jina-reranker-v2-base-multilingual"
    top_n: 30                                 # リランク前に dense で取る候補数（→ top_k 件に精選）

pricing:                              # usage_log のコスト推定に使う単価（USD/100万トークン）
  "google/gemini-2.5-flash": {input: 0.30, output: 2.50}
  "moonshotai/kimi-k2-0905": {input: 0.60, output: 2.50}
  "text-embedding-3-small":  {input: 0.02, output: 0.0}
  "jina-reranker-v2-base-multilingual": {input: 0.02, output: 0.0}  # ※概算・要更新

worker:
  poll_interval_seconds: 10  # ingest_jobs キューの確認間隔（秒）
  sync_interval_hours: 24    # 定期syncの間隔（最後の取り込み完了からの経過時間）
```

> `pricing` は推定コスト算出用（`src/usage.py`）。価格は変動するので最新値に各自で更新する。
> 掲載が無いモデルはコスト0で計上される（トークン数の記録は残る）。

> Dify / Ollama 関連のセクションは廃止した（2026-06-11）。
> 旧設定は git 履歴と `dify/waiwai-oracle.yml`（移行元プロンプトの記録）を参照。

## .env

```env
DISCORD_TOKEN=your-discord-bot-token
OPENAI_API_KEY=your-openai-api-key   # contextualizer.py / embedding で使用（openai.api_key が空の場合）
POSTGRES_PASSWORD=oracle             # composeのpostgresサービスのパスワード
DATABASE_URL=postgresql://oracle:oracle@localhost:5432/oracle  # ホストから手動スクリプトを実行する場合
# OPENROUTER_API_KEY=...             # RAG用LLM（config.yml の openai.api_key が空の場合）
# ORACLE_API_URL=http://localhost:8000  # Bot → APIサーバ接続先（composeでは自動設定）
# QDRANT_URL=http://qdrant:6333         # Qdrant接続先オーバーライド（composeでは自動設定）
# TEST_DATABASE_URL=...                 # pytest用DB接続先（デフォルト: localhost:5432/oracle_test）
ADMIN_PASSWORD=change-me              # 管理ポータル（src/admin）のログインパスワード（未設定だとログイン不可）
# ADMIN_SESSION_SECRET=...             # セッション署名鍵（任意・未設定なら ADMIN_PASSWORD から導出）
```

> コンテナ内の `DATABASE_URL` は docker-compose.yml の `environment` で
> `postgres` サービス向きに上書きされるため、.env の値はホスト実行時のみ使われる。

## 分離ルール

| 種別 | ファイル | Gitコミット |
|---|---|---|
| 動作パラメータ | config.yml | ✅ OK |
| APIキー・トークン・接続文字列 | .env | ❌ 必ずgitignore |

## Docker環境での読み込み

- `config.yml` → コンテナ内 `/app/config.yml` にマウント
- `.env` → `docker-compose.yml` の `env_file` で読み込み
