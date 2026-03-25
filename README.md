# waiwai-oracle

Discordサーバーの全メッセージをRAG化し、チャットボットで回答するPOCプロジェクト。

## 概要

Discordサーバー「waiwai」の過去チャットログ（約27,000件）を取得・チャンク化し、[Dify](https://dify.ai/) のナレッジベースに投入。ユーザーの質問に対してRAG検索で回答するチャットボットを構築しています。

## アーキテクチャ

```
Discord API → crawler.py → SQLite → chunker.py → contextualizer.py → exporter.py → Dify
```

### パイプライン

| Phase | スクリプト | 概要 |
|---|---|---|
| 0 | `dry_run.py` | メッセージ数カウント（取得なし） |
| 1 | `crawler.py` | Discord全メッセージ → SQLite |
| 2 | `chunker.py` | 時間ギャップ方式でチャンク生成 |
| 2.5 | `contextualizer.py` | LLMで各チャンクにコンテキスト付与 |
| 3 | `exporter.py` | チャンク → テキストファイル出力 |

### Discord Bot（くもちゃん）

Dify Chatflow APIと連携するDiscord Bot。SSE streamingで応答を取得します。

## セットアップ

### 必要なもの

- Python 3.11+
- Docker / Docker Compose
- Discord Bot トークン
- Dify（セルフホスト）
- OpenAI API キー（contextualizer用）

### インストール

```bash
git clone https://github.com/aigamoid/waiwai-oracle.git
cd waiwai-oracle

# 環境変数を設定
cp .env.example .env
cp config.yml.example config.yml
# .env と config.yml を編集

# Dockerで実行
docker compose up -d
docker compose run oracle python dry_run.py
```

### Discord Bot

```bash
cd moimoichan_Discordbot
pip install -r requirements.txt
cp config.yml.example config.yml
# config.yml を編集（Dify APIエンドポイント等）
python bot.py
```

## 技術スタック

- **言語**: Python 3.11+
- **Discord**: discord.py
- **DB**: SQLite
- **RAG基盤**: Dify（セルフホスト）
- **Embedding**: OpenAI text-embedding-3-small
- **LLM**: OpenRouter経由（Gemini 2.0 Flash / Kimi K2 等）

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | アーキテクチャ・ディレクトリ構成 |
| [docs/SCHEMA.md](docs/SCHEMA.md) | SQLiteスキーマ・メタデータ仕様 |
| [docs/CONFIG.md](docs/CONFIG.md) | 設定ファイル項目説明 |
| [docs/DEVLOG.md](docs/DEVLOG.md) | 開発ログ |
