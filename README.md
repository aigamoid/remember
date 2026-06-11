# waiwai-oracle

Discordサーバーの全メッセージをRAG化し、チャットボットで回答するPOCプロジェクト。

## 概要

Discordサーバー「waiwai」の過去チャットログ（約27,000件）を取得・チャンク化し、[Qdrant](https://qdrant.tech/) ベクトルDBに登録。ユーザーの質問に対してRAG検索で回答するチャットボットを構築しています。

## アーキテクチャ

```
Discord API → crawler.py → SQLite → chunker.py → contextualizer.py → indexer.py → Qdrant
                                                                                      ↑
Discord Bot（@メンション） → FastAPI（/chat） → RAGエンジン（書き換え→検索→回答生成）──┘
```

### パイプライン

| Phase | スクリプト | 概要 |
|---|---|---|
| 0 | `dry_run.py` | メッセージ数カウント（取得なし） |
| 1 | `crawler.py` | Discord全メッセージ → SQLite |
| 2 | `chunker.py` | 時間ギャップ方式でチャンク生成 |
| 2.5 | `contextualizer.py` | LLMで各チャンクにコンテキスト付与 |
| 3 | `exporter.py` | チャンク → テキストファイル出力（旧Dify用・任意） |
| 4 | `indexer.py` | チャンク → embedding → Qdrant 登録 |

### フロントエンド（2モード）

- **Discord Bot（わいわいちゃん）**: @メンションで過去ログに基づいた回答を返します
- **CLI（動作確認用）**: `python chat_cli.py` でターミナルから対話できます

どちらも同じRAG API（FastAPI `/chat`）を呼ぶ薄いクライアントです。

## セットアップ

### 必要なもの

- Python 3.11+
- Docker / Docker Compose
- Discord Bot トークン
- OpenAI API キー（embedding / contextualizer用）
- OpenRouter API キー（Query Rewriter / 回答LLM用）

### インストール

```bash
git clone https://github.com/aigamoid/waiwai-oracle.git
cd waiwai-oracle

# 環境変数を設定
cp .env.example .env
cp config.yml.example config.yml
cp moimoichan_Discordbot/config.yml.example moimoichan_Discordbot/config.yml
# .env と config.yml を編集

# 取り込みパイプライン（初回）
docker compose run oracle python dry_run.py
docker compose run oracle python crawler.py
docker compose run oracle python chunker.py
docker compose run oracle python contextualizer.py
docker compose run oracle python indexer.py

# サービス起動（Qdrant + RAG API + Discord Bot）
docker compose up -d qdrant api bot
```

## 技術スタック

- **言語**: Python 3.11+
- **Discord**: discord.py
- **DB**: SQLite + Qdrant（ベクトルDB）
- **RAG**: FastAPI + 自前エンジン（クエリ書き換え→ベクトル検索→回答生成）
- **Embedding**: OpenAI text-embedding-3-small
- **LLM**: OpenRouter経由（Query Rewriter: Gemini 2.5 Flash / 回答: Kimi K2）

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | アーキテクチャ・ディレクトリ構成 |
| [docs/SCHEMA.md](docs/SCHEMA.md) | SQLiteスキーマ・メタデータ仕様 |
| [docs/CONFIG.md](docs/CONFIG.md) | 設定ファイル項目説明 |
| [docs/DEVLOG.md](docs/DEVLOG.md) | 開発ログ |
