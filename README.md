# waiwai-oracle (codename: remember)

Discordサーバーの過去ログをRAG化し、Botが質問に回答するマルチテナント対応プロジェクトです。
管理者が許可したチャンネルだけを取り込み、`guild_id` でデータを分離します。

> リブランド方針: プロダクト呼称は段階的に `remember` へ移行中です。  
> 2026-06 時点では管理ポータル（`src/admin`）の表示名を `remember` に統一済みです。

## 何ができるか

- Discordの過去ログを自動取り込み（opt-in）
- 質問時に RAG 検索して回答（Discord Bot / CLI 共通API）
- チャンネル許可取り消し・Bot退出時のデータ削除
- 利用量と推定コストの記録（`usage_log`）
- 管理ポータルでサーバー/ジョブ/コストを可視化

## 全体アーキテクチャ

```text
/oracle allow|sync（管理者）
  -> ingest_jobs (Postgres)
  -> worker がジョブ実行
     1) crawl        Discord -> messages
     2) chunk        messages -> chunk_index
     3) contextualize chunk -> context_text
     4) index        embedding -> Qdrant

質問（Discord @mention / CLI）
  -> FastAPI /chat
  -> Query Rewriter -> embedding -> Qdrant検索 -> 回答LLM
  -> answer + sources を返却
```

## 取り込みパイプライン

| Phase | モジュール | 概要 |
|---|---|---|
| 0 | `dry_run.py` | メッセージ件数見積もり（取得なし） |
| 1 | `crawler.py` | 許可チャンネルの差分取得 -> Postgres |
| 2 | `chunker.py` | 時間ギャップ方式でチャンク化 |
| 2.5 | `contextualizer.py` | 各チャンクに `context_text` を付与 |
| 3 | `exporter.py` | `output/*.txt` 出力（旧Dify用・任意） |
| 4 | `indexer.py` | embedding して Qdrant に登録 |

通常運用では `worker.py`（`src/worker.py`）が `ingest_jobs` を処理し、Phase 1 -> 2 -> 2.5 -> 4 を自動実行します。

## 回答フロー（RAG API）

- API: `src/api.py` (`POST /chat`, `GET /health`)
- エンジン: `src/rag/engine.py`
- 主な流れ:
  1. Query Rewriter（OpenRouter）
  2. embedding + Qdrant検索（`guild_id` フィルタ）
  3. 回答生成（OpenRouter）
  4. usage/cost 記録（`src/usage.py` -> `usage_log`）

補足:
- 会話履歴（`history`）を受け取るマルチターン対応あり（呼び出し側で履歴保持）
- 日次クォータ判定（超過時は案内文を返す fail-open 設計）
- 任意でリランカー（Jina）を有効化可能

## フロントエンド（2モード）

- Discord Bot: `moimoichan_Discordbot/`
- CLI: `chat_cli.py`

どちらも同じ `POST /chat` を呼ぶ薄いクライアントです。

## Discord管理コマンド

| コマンド | 動作 |
|---|---|
| `/oracle allow #channel` | チャンネル許可 + 取り込みジョブ投入 |
| `/oracle allowall` | 全チャンネルを一括許可 + 取り込みジョブ投入（**MAXプラン限定**） |
| `/oracle deny #channel` | 許可取り消し + 取り込み済みデータ削除ジョブ投入 |
| `/oracle sync` | 差分取り込みジョブ投入 |
| `/oracle status` | 許可チャンネル/件数/最新ジョブを確認 |

Botをサーバーから外すと、その `guild_id` のデータは削除ジョブで全削除されます。

## セットアップ

### 1. 前提

- Python 3.11+
- Docker / Docker Compose
- Discord Bot Token
- OpenAI API Key（embedding/contextualizer）
- OpenRouter API Key（rewriter/answer）

### 2. 設定ファイル作成

```bash
git clone https://github.com/aigamoid/waiwai-oracle.git
cd waiwai-oracle

cp .env.example .env
cp config.yml.example config.yml
cp moimoichan_Discordbot/config.yml.example moimoichan_Discordbot/config.yml
```

編集ポイント:
- `.env`
  - `DISCORD_TOKEN`
  - `OPENAI_API_KEY`
  - `OPENROUTER_API_KEY`
  - `ADMIN_PASSWORD`（管理ポータルログイン用）
- `config.yml`
  - `rag.*`（モデル・`top_k`・履歴設定・リランカー）
  - `worker.sync_interval_hours`
- `moimoichan_Discordbot/config.yml`
  - `oracle.api_url`
  - `discord.mention_only`

### 3. 起動

```bash
docker compose up -d postgres qdrant api admin worker bot
```

- API: `http://localhost:8000`
- 管理ポータル: `http://localhost:8001`

### 4. 動作確認

1. BotをDiscordサーバーへ招待
2. 管理者が `/oracle allow #channel` を実行
3. `/oracle status` で取り込み進捗を確認
4. Botにメンションして質問

## テスト

```bash
docker compose up -d postgres
.venv/bin/python -m pytest tests/
```

DB系テストは実Postgres（`oracle_test`）を使います。DB未起動時は該当テストが skip されます。

## 運用メモ

- ワーカー進捗は `ingest_jobs` に記録されます
- 利用量/コストは `usage_log` に記録されます（記録失敗でも回答は継続）
- 単価は `config.yml` の `pricing`（USD/100万トークン）を更新して使ってください

## 技術スタック

- Python 3.11+
- discord.py
- FastAPI / Uvicorn / Jinja2
- Postgres（メタデータ・ジョブキュー）
- Qdrant（ベクトルDB）
- OpenAI（embedding / contextualizer）
- OpenRouter（rewriter / answer）

## 主要ドキュメント

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/DIAGRAMS.md](docs/DIAGRAMS.md)
- [docs/SCHEMA.md](docs/SCHEMA.md)
- [docs/CONFIG.md](docs/CONFIG.md)
- [docs/OPEN_ISSUES.md](docs/OPEN_ISSUES.md)
- [docs/DEVLOG.md](docs/DEVLOG.md)
