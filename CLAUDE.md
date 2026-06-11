# waiwai-oracle

Discordサーバーの全メッセージをRAG化し、チャットボットで回答するPOCプロジェクト。

## フェーズ構成

| Phase | スクリプト | 概要 |
|---|---|---|
| 0 | `dry_run.py` | メッセージ数カウントのみ（本取得なし） |
| 1 | `crawler.py` | Discord全メッセージ → SQLite |
| 2 | `chunker.py` | 時間ギャップ方式でチャンク生成 |
| 2.5 | `contextualizer.py` | LLMで各チャンクに context_text を付与 |
| 3 | `exporter.py` | chunk_index → output/*.txt へファイル出力（旧Dify用・任意） |
| 4 | `indexer.py` | chunk_index → embedding → Qdrant 登録 |

実行順: `dry_run.py` → `crawler.py` → `chunker.py` → `contextualizer.py` → `indexer.py`

## 回答サーバ（RAG API）

- `src/api.py`（FastAPI）が `POST /chat` で質問を受け、`src/rag/engine.py` が
  クエリ書き換え → Qdrant検索 → LLM回答を行う（旧Difyフローの自前実装）
- Discord Bot（`moimoichan_Discordbot/`）はこのAPIを呼ぶ
- 起動: `docker compose up -d qdrant api`（Botは `bot` サービス）

## 詳細ドキュメント

- アーキテクチャ・ファイル構成 → `docs/ARCHITECTURE.md`
- SQLiteスキーマ・メタデータ仕様 → `docs/SCHEMA.md`
- 設定ファイル項目説明 → `docs/CONFIG.md`
- 未解決事項・TODO → `docs/OPEN_ISSUES.md`

## Claude Codeへの注意事項

- **新フェーズ開始前・プランレビュー前に必ず `docs/OPEN_ISSUES.md` を読むこと。**
  過去フェーズで確定した設計決定（例: Difyメタデータフィルタ不使用）がここに記録されている。
  読まずにプランを立てると、決定済み事項を「抜け」として誤指摘するリスクがある。

### ファイルを追加・削除・改名したときのドキュメント更新ルール

以下のドキュメントに古い名前が残っていないか確認し、必要なら更新すること。

| 確認対象 | チェック内容 |
|---|---|
| `CLAUDE.md`（このファイル） | フェーズ構成表のスクリプト名、技術スタック |
| `docs/ARCHITECTURE.md` | ディレクトリ構成ツリー、データフロー図 |
| `docs/SCHEMA.md` | カラム説明コメント（`xxx.py が〜` 形式） |
| `docs/CONFIG.md` | 設定項目の説明 |
| 変更ファイルの docstring | 「〇〇から使用」形式の呼び出し元ファイル名 |

**自動チェック（pre-commit hook）**:
`scripts/check_docs.py` が CLAUDE.md と docs/ARCHITECTURE.md 内の `.py` 参照を検証する。
初回セットアップ時に以下を実行すること:
```sh
sh scripts/install_hooks.sh
```

## Git運用ルール

- ブランチ戦略: GitFlow
- 初回ブランチ: `feature/waiwai-oracle`
- コミット粒度: **1ファイル単位**
- **プッシュは人間が手動で行う。Claude Codeはpushコマンドを実行しないこと**

## 技術スタック

- Python 3.11+
- discord.py / SQLite / Docker
- Qdrant（ベクトルDB・セルフホスト） + FastAPI（RAG回答API）
- OpenAI API（embedding: text-embedding-3-small / `contextualizer.py` の context_text 生成）
- OpenRouter（Query Rewriter: Gemini 2.5 Flash / 回答LLM: Kimi K2）
- ※Dify は廃止済み（`dify/waiwai-oracle.yml` は移行元プロンプトの記録として保持）

## 作業ログ

`docs/DEVLOG.md` 参照
