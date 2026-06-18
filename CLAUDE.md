# waiwai-oracle

> **コードネーム: remember**（このプロダクトの正式呼称）。
> 段階的に `waiwai-oracle` → `remember` へ改名していく方針。
> 2026-06-15 時点では**管理ポータル（src/admin）の表示名**を `remember` に統一済み。
> 2026-06-17 には**Botの回答キャラ名も「れみちゃん」にリブランド**（OI-15）。
> リポジトリ名・compose・Qdrantコレクション名（`waiwai_chunks`）等の全体改名は未実施
> （Qdrantコレクション名はデータ移行が絡むため別途要相談）。
> なお「わいわい」はテナントのDiscordサーバー名・「れみちゃん」はBotの回答キャラ名であり、
> プロダクト名 `remember` とは別物。

Discordサーバーの過去ログをRAG化し、チャットボットで回答するPOCプロジェクト。
マルチテナント対応済み（サーバーごとに opt-in 取り込み・guild_id でデータ分離）。

## 取り込みパイプライン

| Phase | モジュール | 概要 |
|---|---|---|
| 0 | `dry_run.py` | メッセージ数カウントのみ（本取得なし） |
| 1 | `crawler.py` | 許可チャンネルのメッセージ → Postgres（差分） |
| 2 | `chunker.py` | 時間ギャップ方式でチャンク生成 |
| 2.5 | `contextualizer.py` | LLMで各チャンクに context_text を付与 |
| 3 | `exporter.py` | chunk_index → output/*.txt へファイル出力（旧Dify用・任意） |
| 4 | `indexer.py` | chunk_index → embedding → Qdrant 登録 |

**通常運用は自動**: Botのスラッシュコマンド（`/oracle allow|deny|sync|status`）が
`ingest_jobs` キューにジョブを積み、常駐ワーカー（`worker.py` → `src/worker.py`）が
Phase 1→2→2.5→4 を順に実行する。定期sync（デフォルト24h毎）もワーカーが行う。
各ルートスクリプトは config.yml の guild_id に対する手動実行用（デバッグ・再構築）。

## 回答サーバ（RAG API）

- `src/api.py`（FastAPI）が `POST /chat` で質問を受け、`src/rag/engine.py` が
  クエリ書き換え → Qdrant検索 → LLM回答を行う（旧Difyフローの自前実装）
- フロントエンドは2モード（両方維持する）:
  - Discord Bot（`moimoichan_Discordbot/`）
  - CLI（`chat_cli.py` ※動作確認用、`python chat_cli.py` で対話）
- 回答時に各 LLM/embedding の利用量を `usage_log` に記録する（`src/usage.py`・OI-14 C）。
  コストは config.yml の `pricing`（USD/100万トークン）から推定。記録失敗は回答を止めない。
- 管理ポータル `src/admin/`（FastAPI+Jinja2・別サービス `admin`・ポート8001）で
  サーバー/ジョブ/利用量・コストを閲覧できる。認証は `.env` の `ADMIN_PASSWORD`。
- 起動: `docker compose up -d postgres qdrant api admin worker`（Botは `bot` サービス）
- テスト: `docker compose up -d postgres` してから `pytest tests/`
  （DB系テストは実Postgresの oracle_test DBを使う。未起動ならskip）

### CI（自動テスト・GitHub Actions）

- **PR作成/更新時・`main`/`develop` への push 時に `pytest` が自動実行される**
  （定義: [.github/workflows/tests.yml](.github/workflows/tests.yml)・2026-06-18 導入 / PR #14）。
  手動で `pytest` する代わりにGitHubが回し、PR画面に ✅/❌ を表示する。
- CI内では Postgres を**サービスコンテナ**（`postgres:16`）で起動し、
  `TEST_DATABASE_URL` で接続先を指定する（conftest.py がこの環境変数を読む）。
- APIキー・config.yml はテストで参照しないため、**GitHub側のシークレット登録は不要**。
- CD（自動デプロイ）は**未導入**。GCP VM への反映は引き続き手動。
- 注意: ローカルでは `test_indexer` の一部がインメモリQdrant共有で稀に揺れるが、
  CI（クリーン環境）では再現せずパスする。コードのバグではない。
- `.github/workflows/` 配下を push するには gh トークンに `workflow` スコープが必要
  （無い場合 `gh auth refresh -h github.com -s workflow` でブラウザ認可）。
- **教訓: semantic conflict に注意**（2026-06-18・CI導入初日に検知）。
  派生元が古い feature ブランチが、共有関数のシグネチャ変更後の develop にマージされると、
  **テキスト衝突は起きないのにテストが壊れる**ことがある（例: `engine.answer` に
  `history` 引数が追加され5要素タプル化されたが、先に分岐していた oi14 のテストが
  4要素のままマージされ CI が赤化 / PR #18 で修正）。古いブランチをマージする前に
  `git merge develop` で最新を取り込み、ローカルで `pytest` を通すこと。

## 詳細ドキュメント

- アーキテクチャ・ファイル構成 → `docs/ARCHITECTURE.md`
- 処理フロー図解（Mermaid） → `docs/DIAGRAMS.md`
- Postgresスキーマ・メタデータ仕様 → `docs/SCHEMA.md`
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
- **PRのマージは必ず人間が行う。Claude CodeはPRの作成（`gh pr create`）まで。
  マージ（`gh pr merge`）はしないこと**（2026-06-18 追加）。
  「マージまでやって」と言われても最終マージは人間に渡し、勝手に `gh pr merge` しない。
- **ドキュメントは PR 不要・develop へ直接コミット可**（2026-06-18 追加）。
  対象: `CLAUDE.md` / `docs/DEVLOG.md` など**コードを含まないドキュメント類**。
  これらは CI もレビューも不要なため、feature ブランチ／PR を作らず
  develop の worktree で直接コミットしてよい（push は従来どおり人間が行う）。
  ※コード（`.py` 等）の変更は引き続き feature ブランチ＋PR を経由すること。
  ※gitignore はしない（全セッション・GCP VM で共有される必要があるため）。

### 複数セッション・並行ブランチ運用（git worktree 必須）

**背景:** 複数の Claude Code セッションが同時に走ることがある。1つの作業ディレクトリで
`git checkout`/`switch` してブランチを切り替えると、**他セッションの作業ツリーを巻き込んで
事故る**（実際にコミットが意図しないブランチに乗る事例が発生・2026-06-16）。これを防ぐため、
**別ブランチの作業は git worktree で物理的に分ける**。

**ルール:**
- メイン作業ディレクトリ（`~/Desktop/waiwai-oracle`）の**チェックアウト中ブランチを勝手に切り替えない**。
- 別ブランチで作業するときは新しい worktree を作る（メインを汚さない）:
  - 既存ブランチ: `git worktree add ../remember-<topic> <branch>`
  - 新規ブランチ: `git worktree add ../remember-<topic> -b feature/<topic>`
  - 例: `git worktree add ../remember-oi18 feature/oi18-mention-resolution`
- 作業前・コミット前に必ず `git branch --show-current` で**今いるブランチを確認**する。
- **1ブランチ＝1 worktree**（gitが同一ブランチの二重チェックアウトを禁止＝衝突を自動で防ぐ）。
- 別の worktree へ commit/push する場合は `git -C <worktree-path> ...` を使い、`cd` でメインを離れない。
- 終わったら `git worktree remove <path>` で撤去（マージ後など）。
- **他セッションが使用中の worktree/ブランチには触れない。** reset/rebase/force-push 等の履歴書き換えは
  単独で行わず、関係セッションと足並みを揃えてから実施する（[[グローバル: 同一スコープは単一ライター]]）。

## 技術スタック

- Python 3.11+
- discord.py（Bot + スラッシュコマンド） / Docker
- Postgres（メタデータ・ジョブキュー / psycopg） + Qdrant（ベクトルDB・セルフホスト）
- FastAPI（RAG回答API）
- OpenAI API（embedding: text-embedding-3-small / `contextualizer.py` の context_text 生成）
- OpenRouter（Query Rewriter: Gemini 2.5 Flash / 回答LLM: DeepSeek V3.2 ※OI-16でKimi K2から変更）
- ※Dify は廃止済み（`dify/waiwai-oracle.yml` は移行元プロンプトの記録として保持）
- ※SQLite は廃止済み（`data/messages.db` は移行元データとして保持。
  `scripts/migrate_sqlite_to_pg.py` で Postgres へ移行済み）

## 作業ログ

`docs/DEVLOG.md` 参照
