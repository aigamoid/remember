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

**通常運用は自動**: Botのスラッシュコマンド（`/oracle allow|allowall|deny|sync|status`）が
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

### CD（自動デプロイ・GitHub Actions）

- **`develop` に push（＝PRマージ）され、かつ pytest が緑のときだけ** `remember-vm` へ自動デプロイされる
  （定義: [.github/workflows/tests.yml](.github/workflows/tests.yml) の `deploy` ジョブ・2026-06-20 導入 / PR #29）。
  PR更新・`main` への push では走らない（`if: push && ref==develop`）。やることは「PRをマージ」だけ。
- 実行場所は **GCP検証機 remember-vm 上の self-hosted runner**（systemdサービスで常駐・label `remember-vm`）。
  VMはTailnet限定（インバウンド）だが、runnerはVMから外向きにGitHubへ接続するため成立する（pull型）。
- デプロイ内容: VM上の `~/remember`（gitクローン）で `git reset --hard origin/develop`
  → `docker compose up -d --build` → `/health` が200を返すまで確認。
  `.env`/`config.yml`/`data/` は **.gitignore 済みなので reset --hard でも保持**される。
- 認証: VMの **read-only SSHデプロイキー**（`~/.ssh/remember_deploy`）で `git fetch`（PATは不使用）。
- **VM停止中（自動停止 JST 2/9/17時）にマージしても、deployジョブはキューで待機し起動時に自動実行**される。
- デプロイ失敗時（ビルド失敗・health NG）は赤化し、**旧コンテナが動き続ける**ので稼働中サービスは守られる。
- 同時マージ対策として `concurrency: deploy-remember-vm` でデプロイは直列化（前のデプロイは中断しない）。

## 詳細ドキュメント

- アーキテクチャ・ファイル構成 → `docs/ARCHITECTURE.md`
- 処理フロー図解（Mermaid） → `docs/DIAGRAMS.md`
- Postgresスキーマ・メタデータ仕様 → `docs/SCHEMA.md`
- 設定ファイル項目説明 → `docs/CONFIG.md`
- **未解決事項・TODO（アクティブ）→ GitHub Issues**（2026-06-22 移行）。
  起票・進捗・クローズは GitHub Issues で管理する（採番は `#NN`）。
- `docs/OPEN_ISSUES.md` は **①OI-XX→#NN インデックス表 ②確定設計決定の記録 ③完了アーカイブ** のみ。
  肥大化したファイル運用を GitHub Issues へ移行した経緯と、旧 `OI-XX` 番号（コードに残存）の
  対応表を保持する（旧番号は OI-54 で凍結）。

## codex-fugu の利用ルール

- **codex-fugu はコストが非常に高いため、勝手に使わない。**
  通常のレビュー・実装・操作には使用しないこと（デフォルトは Claude Code / 通常の Codex / Aider）。
- **ユーザーが明示的に「codex-fugu を使って」と求めたときだけ**起動し、レビューや操作を行う。
  いざという時（難所・重要局面）の切り札として温存する。
- ユーザーから明示の指示が無い限り、提案・自動起動も含めて codex-fugu には触れない。

## Fable 5 の利用ルール

Fable 5（`claude-fable-5`）は Opus 4.8 の上に位置する最上位モデル。**usage 制限が厳しいため、
codex-fugu と同様に「難所の切り札」として温存し、日常作業では使わない**。切り替えは `/model` で行う。

### Fable 5 を使う場面（重要局面のみ）
- **アーキテクチャ級の設計判断**（例: Qdrantコレクション改名・全体リネーム計画・本番化設計など、
  判断を誤ると本番データやデータ移行に波及する変更の方針決め）。
- **原因が掴めない難デバッグ**の「どこが悪いか特定する」フェーズ（実装フェーズは別モデルへ）。
- **高リスク変更の Judge / 最終レビュー**（3エージェント構成のモード2 Judge 役のうち重い局面）。
- **仕様が曖昧な新フェーズのプラン立案**（1セッションで方針を固め、実装は DeepSeek/Codex に渡す）。

### Fable 5 を使わない場面（Opus/Sonnet または DeepSeek に落とす）
- ドキュメント更新（DEVLOG・CLAUDE.md・docs/）、テスト実行・CI確認・PR作成などの定型 Git 作業。
- 小粒バグ修正（モード1相当。そもそも Aider/DeepSeek 担当）。
- コードベースの探索・調査だけのセッション。

### usage を無駄にしないコツ
- **1ターンに全仕様を詰める**（TASK/SCOPE/DOD/制約を最初のメッセージにまとめる）。小出しの往復は消費増。
- **セッションを役割で切る**。設計判断が終わったら実装は別モデルで新セッションを開始する
  （長大コンテキストの持ち越しで消費が加速するため）。
- **探索は安く済ませる**。対象ファイル・Issue番号を事前特定してから Fable に投入する。
- **成果物を残して切り上げる**。設計判断は `docs/OPEN_ISSUES.md`（確定設計決定）や Issue に書き残し、
  続きは安いモデル・エージェントが引き継げる形にする。

### 配分の目安
コスト戦略「DeepSeek 70〜80% / Claude 20〜30%」の Claude 側をさらに分割し、
**Fable 5 は全体の 5〜10%（月に数回の重要局面のみ）、日常の Claude Code 作業は Opus/Sonnet** を既定とする。

## Claude Codeへの注意事項

- **新フェーズ開始前・プランレビュー前に必ず、関連する GitHub Issues と
  `docs/OPEN_ISSUES.md`（確定設計決定の節）を読むこと。**
  アクティブな課題は GitHub Issues（`gh issue list` / `gh issue view <#NN>`）にある。
  過去フェーズで確定した設計決定（例: Difyメタデータフィルタ不使用）は `docs/OPEN_ISSUES.md` に残る。
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
- **課題の採番は GitHub Issue の `#NN` を正典とする**（2026-06-22 移行）。
  独自の `OI-XX` 採番は **OI-54 で凍結**（手動採番の番号衝突を避けるため）。新規課題は GitHub Issue を立てる。
  - コミット・PR・本文での参照は **新規は `#NN`**（例: `fix: purge範囲を拡張 (#7)`）。
  - **既存コード内の `OI-XX` 参照は書き換えない**（履歴の一貫性のため温存）。既存参照を修正する場合のみ
    `OI-44 (#7)` のように `OI-XX (#NN)` を併記してよい。対応は `docs/OPEN_ISSUES.md` のインデックス表で辿る。
- **PR は対応する GitHub Issue と必ず紐づける**（2026-06-22 追加）。
  - PR 本文に **クロージングキーワード**を入れる: `Closes #NN`（または `Fixes #NN` / `Resolves #NN`）。
    例: `gh pr create --title "fix: purge範囲を拡張 (#31)" --body "Closes #31\n\n..."`。
  - **重要（#73・2026-06-29）: GitHub標準のクロージングキーワードは「デフォルトブランチ（`main`）への
    マージ時のみ」自動クローズが発火する。** 本リポジトリは GitFlow で PR を `develop` にマージするため、
    `Closes #NN` を正しく書いても**標準機能では自動クローズされない**（実際に5件取り残された）。
    そのため `develop` への PR マージ時は **[.github/workflows/close-linked-issues.yml](.github/workflows/close-linked-issues.yml)**
    が PR 本文の `Closes/Fixes/Resolves #NN` を解析して対象 Issue を自動クローズする（この workflow が代替）。
    キーワードの記法（カンマ列挙だけでは2件目が閉じない等）は標準と同じく**各番号にキーワードを付ける**こと。
  - クローズせず**関連だけ**示したい場合は本文に `#NN` と書く（参照リンクのみ。epic への言及など）。
  - 旧 `OI-XX` で切ったブランチ（`feature/oiXX-*`）はそのままでよい。コードの `OI-XX` ↔ Issue `#NN` は
    `docs/OPEN_ISSUES.md` のインデックス表で対応する。1つの PR が複数 Issue を閉じるなら
    `Closes #38, closes #39` のように**各番号にキーワードを付ける**（カンマ列挙だけでは2件目が閉じない）。
- **feature ブランチの push と PR 作成（`gh pr create`）は Claude Code が実施してよい**
  （2026-06-19 更新）。`feature/*` ブランチを `git push` し、PR 作成までを Claude Code が行う。
  ※旧ルール「プッシュは人間が手動で行う」はこの範囲で緩和（feature ブランチに限る）。
  ※`main` / `develop` への直接 push は引き続き人間が行う（下記ドキュメント直コミット含む）。
- **PRのマージは必ず人間が行う。Claude CodeはPRの作成（`gh pr create`）まで。
  マージ（`gh pr merge`）はしないこと**（2026-06-18 追加）。
  「マージまでやって」と言われても最終マージは人間に渡し、勝手に `gh pr merge` しない。
- **ドキュメントは PR 不要・develop へ直接コミット可**（2026-06-18 追加）。
  対象: `CLAUDE.md` / `docs/DEVLOG.md` など**コードを含まないドキュメント類**。
  これらは CI もレビューも不要なため、feature ブランチ／PR を作らず
  develop の worktree で直接コミットしてよい（develop への push は従来どおり人間が行う）。
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
