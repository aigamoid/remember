# waiwai-oracle

Discordサーバーの過去ログをRAG化し、チャットボットで回答するPOCプロジェクト。

## 概要

Botを導入したDiscordサーバーのチャットログを自動で取り込み・ベクトル化し、
ユーザーの質問にRAG検索で回答するチャットボットです。
管理者が許可（opt-in）したチャンネルだけを読み、サーバーごとにデータを完全分離します。

## アーキテクチャ

```
/oracle allow（管理者） → ジョブキュー(Postgres) → worker.py が自動実行:
    Discord API → crawl → chunk → contextualize → embedding → Qdrant
                                                                  ↑
Discord Bot（@メンション） → FastAPI（/chat） → RAGエンジン（書き換え→検索→回答生成）
```

### 取り込みパイプライン

| Phase | モジュール | 概要 |
|---|---|---|
| 1 | `crawler.py` | 許可チャンネルのメッセージ → Postgres（差分） |
| 2 | `chunker.py` | 時間ギャップ方式でチャンク生成 |
| 2.5 | `contextualizer.py` | LLMで各チャンクにコンテキスト付与 |
| 3 | `exporter.py` | チャンク → テキストファイル出力（旧Dify用・任意） |
| 4 | `indexer.py` | チャンク → embedding → Qdrant 登録 |

通常運用では `worker.py`（常駐ワーカー）が Bot のスラッシュコマンドや定期syncを
きっかけに Phase 1→2→2.5→4 を自動実行する。各 `*.py` はデバッグ・再構築用の手動実行にも使える。

### 管理コマンド（Discord・サーバー管理権限が必要）

| コマンド | 動作 |
|---|---|
| `/oracle allow #channel` | チャンネルの読み取りを許可し、取り込みを開始 |
| `/oracle deny #channel` | 許可を取り消し、取り込み済みデータを削除 |
| `/oracle sync` | 新着メッセージを今すぐ差分取り込み |
| `/oracle status` | 取り込み状況・最新ジョブを表示 |

Botをサーバーから外すと、そのサーバーのデータは自動で全削除されます。

### フロントエンド（2モード）

- **Discord Bot（れみちゃん）**: @メンションで過去ログに基づいた回答を返します
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

# 全サービス起動（Postgres + Qdrant + RAG API + ワーカー + Discord Bot）
docker compose up -d postgres qdrant api worker bot
```

あとは Discord サーバーに Bot を招待し、管理者が `/oracle allow #チャンネル` を
実行すれば取り込みが始まります。

### テスト

```bash
docker compose up -d postgres   # DB系テストが実Postgres（oracle_test DB）を使う
.venv/bin/python -m pytest tests/
```

## 技術スタック

- **言語**: Python 3.11+
- **Discord**: discord.py（Bot + スラッシュコマンド）
- **DB**: Postgres（メタデータ・ジョブキュー） + Qdrant（ベクトルDB）
- **RAG**: FastAPI + 自前エンジン（クエリ書き換え→ベクトル検索→回答生成）
- **Embedding**: OpenAI text-embedding-3-small
- **LLM**: OpenRouter経由（Query Rewriter: Gemini 2.5 Flash / 回答: Kimi K2）

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | アーキテクチャ・ディレクトリ構成 |
| [docs/DIAGRAMS.md](docs/DIAGRAMS.md) | 処理フロー・設計のMermaid図解 |
| [docs/SCHEMA.md](docs/SCHEMA.md) | Postgresスキーマ・Qdrantペイロード仕様 |
| [docs/CONFIG.md](docs/CONFIG.md) | 設定ファイル項目説明 |
| [docs/DEVLOG.md](docs/DEVLOG.md) | 開発ログ |
