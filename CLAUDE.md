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

## Claude Codeへの注意事項

- **新フェーズ開始前・プランレビュー前に必ず `docs/OPEN_ISSUES.md` を読むこと。**
  過去フェーズで確定した設計決定（例: Difyメタデータフィルタ不使用）がここに記録されている。
  読まずにプランを立てると、決定済み事項を「抜け」として誤指摘するリスクがある。

## Git運用ルール

- ブランチ戦略: GitFlow
- 初回ブランチ: `feature/waiwai-oracle`
- コミット粒度: **1ファイル単位**
- **プッシュは人間が手動で行う。Claude Codeはpushコマンドを実行しないこと**

## 技術スタック

- Python 3.11+
- discord.py / SQLite / Docker
- Dify Knowledge API（アップロード先）
- OpenAI `text-embedding-3-small`（Embedding ※旧: Ollama bge-m3、Difyプラグインバグで変更）

## チャンキング設計メモ（Claude Codeへ）

- **現状**: uploader.py は messages テーブルを直接連結して Dify に送信（chunk_index 不使用）
- **問題**: セパレータ `\n\n` = メッセージ結合文字のため 1メッセージ = 1チャンク
- **検討中**: セマンティックチャンキング（Python 側で事前分割）
  - Dify にはセマンティック分割機能なし → uploader 側で embedding して境界検出
  - 実装したら `--clean` で全チャンネル再アップロードが必要
- **作業ログ** → `docs/DEVLOG.md` 参照
