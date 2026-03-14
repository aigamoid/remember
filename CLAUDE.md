# waiwai-oracle

Discordサーバーの全メッセージをRAG化し、チャットボットで回答するPOCプロジェクト。

## フェーズ構成

| Phase | スクリプト | 概要 |
|---|---|---|
| 0 | `dry_run.py` | メッセージ数カウントのみ（本取得なし） |
| 1 | `crawler.py` | Discord全メッセージ → SQLite |
| 2 | `chunker.py` | スライディングウィンドウでチャンク生成 |
| 3 | `uploader.py` | Dify Knowledge APIへアップロード |

実行順: `dry_run.py` → `crawler.py` → `chunker.py` → `uploader.py`

## 詳細ドキュメント

- アーキテクチャ・ファイル構成 → `docs/ARCHITECTURE.md`
- SQLiteスキーマ・メタデータ仕様 → `docs/SCHEMA.md`
- 設定ファイル項目説明 → `docs/CONFIG.md`
- 未解決事項・TODO → `docs/OPEN_ISSUES.md`

## Git運用ルール

- ブランチ戦略: GitFlow
- 初回ブランチ: `feature/waiwai-oracle`
- コミット粒度: **1ファイル単位**
- **プッシュは人間が手動で行う。Claude Codeはpushコマンドを実行しないこと**

## 技術スタック

- Python 3.11+
- discord.py / SQLite / Docker
- Dify Knowledge API（アップロード先）
- Ollama `bge-m3`（Embedding、Windows機 via Tailscale）
