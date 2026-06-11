# 設定ファイル仕様

## config.yml

```yaml
guild_id: 123456789          # 対象DiscordサーバーのID

crawl:
  exclude_channels:          # 除外チャンネル名リスト
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
  top_k: 10                                   # 検索で取得するチャンク数
  guild_name: "わいわい"                       # 回答プロンプトに埋め込むサーバー名

# 以下は現行コードで未使用（将来・旧設定として保持）
# dify:
#   api_endpoint: ...      # Dify廃止（Qdrant + 自前APIに移行）のため不要
# ollama:
#   endpoint: ...          # bge-m3 embedding 廃止（Difyプラグインバグのため）のため不要
```

## .env

```env
DISCORD_TOKEN=your-discord-bot-token
OPENAI_API_KEY=your-openai-api-key   # contextualizer.py / embedding で使用（openai.api_key が空の場合）
# OPENROUTER_API_KEY=...             # RAG用LLM（config.yml の openai.api_key が空の場合）
# ORACLE_API_URL=http://localhost:8000  # Bot → APIサーバ接続先（composeでは自動設定）
# QDRANT_URL=http://qdrant:6333         # Qdrant接続先オーバーライド（composeでは自動設定）
```

## 分離ルール

| 種別 | ファイル | Gitコミット |
|---|---|---|
| 動作パラメータ | config.yml | ✅ OK |
| APIキー・トークン | .env | ❌ 必ずgitignore |

## Docker環境での読み込み

- `config.yml` → コンテナ内 `/app/config.yml` にマウント
- `.env` → `docker-compose.yml` の `env_file` で読み込み
