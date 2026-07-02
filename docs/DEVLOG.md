# DEVLOG

Phase ごとの作業記録・設計判断ログ。

---

## 2026-06-30 — 公開/課金前の明示同意ログ実装（#41 / OI-48・法務）

`/oracle allow`・`allowall` は opt-in だが、「過去ログ本文の保存」「外部LLM APIへの送信」
「料金・quota・削除ポリシー」への**明示同意ログ**を取っていなかった（公開・有料化に事実上必須・P1）。
初回の許可操作時に同意文をボタンUIで提示し、同意した管理者ID・日時・対象ch・規約版を新テーブル
`consent_log` に記録するようにした。

### 変更
| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/db.py` | `consent_log` テーブル追加（後付けマイグレーション節）。`record_consent()` / `has_consented()`（サーバー×規約版でEXISTS判定） |
| 2 | `moimoichan_Discordbot/store.py` | `Store.has_consented` / `Store.record_consent`（既存 `_call` ラッパー） |
| 3 | `moimoichan_Discordbot/bot.py` | `CONSENT_TERMS_VERSION` 定数・`_CONSENT_TEXT`（allow）・`_CONSENT_TEXT_ALL`（allowall強調）・`ConsentView`（同意/やめるの2ボタン）。`allow`/`allowall` を本処理 `_do_allow`/`_do_allowall` に分離し、未同意時のみ同意UIを挟む |
| 4 | `tests/conftest.py` | `_TRUNCATE` に `consent_log` を追加 |
| 5 | `tests/test_consent.py`（新規） | record→has_consented／規約版違い→再同意／channels JSONB往復／Store経路 |
| 6 | `tests/test_bot_help.py` | 定数存在・同意文の必須3項目・`ConsentView` 生成の軽い検証 |
| 7 | `docs/SCHEMA.md` | `consent_log` を追記 |

### 決定事項（ユーザー確認済み）
- **同意UIはボタン式**（`discord.ui.View`・本リポジトリ初のView導入）。`interaction_check` で
  操作を始めた管理者本人だけが押せる。同意ボタンで `record_consent`→本処理 `on_agree` を実行。
- **記録単位はサーバー×規約版**。現行版に一度同意すれば以降は同意文を出さず即実行し、
  `CONSENT_TERMS_VERSION` を上げたときだけ再同意を求める。consent_log は監査証跡として全件保持。
- `allowall` は全ch対象のため**より強い確認文面**（全チャンネルが対象になることを明示）。
- 規約版はコード定数で管理（`bot.py`）。文面・対象を変えたら版を上げる運用。

## 2026-06-30 — 会話履歴の話者取り違え修正(#63)：発話者ラベル＋SPEAKER_SECTION強化

同一チャンネルで **ユーザーA→B** と続けて話すと、B への会話履歴に A との会話が残り、**B を A と取り違えて誤答**する事象（実例: aigamoid と6ターン会話後に さみさみ の「さみって誰」へ「さみさみって…aigamoidのことだよ」と誤答）。MAGI **4者レビュー**（Codex/Aider/**codex-fugu**）で PASS → PR #76。

### 根本原因（3層）
1. 会話履歴がチャンネル単位で共有（発話者別でない）→ 別ユーザーの直前会話が次の発話者に渡る。
2. 履歴に発話者名ラベルが無い → モデルが多数派（前ユーザー）に引きずられ、現発話者ラインと矛盾。
3. Query Rewriter が前ユーザー文脈を読み `[NO_SEARCH]` → ログから本人を探す機会も無し。

### 変更（Issue推奨 B＋C を採用・D は別軸でフォローアップ #75）
| # | ファイル | 内容 |
|---|---|---|
| 1 | `moimoichan_Discordbot/bot.py` | `_remember_turn` に `speaker` 引数。user ターンを `{"role","content","speaker":display_name}` で保存し、次ターンへ発話者名を引き継ぐ |
| 2 | `src/rag/engine.py` | `_prep_history` が `speaker` を保持（content は生・バジェット従来通り）。新ヘルパ `_label_history()` が **LLM送信直前**に user 発言を `"名前: 本文"` に描画。`_sanitize_speaker()`（単一行化・制御文字除去・24字上限）。`SPEAKER_SECTION` の現発話者にも同サニタイズを適用 |
| 3 | `src/rag/prompts.py` | `SPEAKER_SECTION` 強化（C）：現発話者が最も確かな情報・履歴は「名前: 」付き・**過去の相手と取り違えない**ことを明示 |
| 4 | `tests/test_rag.py` | ラベル描画／後方互換（speaker無は不変）／assistant無ラベル／非破壊／本文＆名前の注入無効化／24字丸め／SPEAKER_SECTIONサニタイズ／A→B統合 の8テスト |

### 決定事項（受容したトレードオフ）
- **履歴は channel 単位のまま分離しない**（案A却下）。理由は**複数人の雑談文脈を失う**ため（Issue明示）。長スレ・多人数での取り違えは C の明示＋ラベルで緩和（根治ではない）。恒久策（履歴分離）の検討は別 issue #75 に回す。
- ラベルは**不変IDでなく display_name**（SPEAKER_SECTION と一貫・れみの口調を保つ）。**重名衝突は許容済み制約**（display_name ベース運用と同等）。
- 注入対策（codex-fugu 指摘）: 名前だけでなく**本文の改行も空白に畳んで 1 ターン=1 行に固定**し、本文に `"別人:"` を仕込む偽装を封じる。`_label_history` は**非破壊**（mimic ガードが参照する `hist_ans` は生のまま）。
- 文字数バジェットはラベル分（最大 ~26字×ターン）を過小評価するが `history_max_chars`(4000) に対し軽微として許容。

### 実行結果
- ローカルは DB 依存（psycopg/qdrant）未インストール＋Docker 未起動のためフル pytest は未実行。構文チェック＋描画ロジックの単体検証は PASS。**フル pytest は CI（PR）で検証**。

### 次のステップ
- D（NO_SEARCH ゲート調整：「〜って誰」等の人物質問で検索を必ず実行）を別 issue として起票・実装。

---

## 2026-06-29 — rewriter応答文混入の修正(#64)：プロンプト強化＋出力長ガード

Query Rewriter が検索語でなく**れみちゃんのペルソナ口調の応答文**を出力する滑り（本番 chat_trace 約90件中4件＝約4-5%）を修正。MAGI 3者レビュー(Codex/Aider)2ラウンドで PASS → PR #72（人間マージ済）。

### 変更（予防＋保険の2本立て）
| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/rag/prompts.py` | REWRITER_SYSTEM_PROMPT に「応答せず検索語のみ出力」制約＋断定/訂正/会話発話の書き換え例3件（#64実例ベース） |
| 2 | `src/rag/engine.py` | `rewrite()` に出力長ガード：`[NO_SEARCH]`でなく `rewriter_max_query_chars`(既定60)超なら応答文混入とみなし**元クエリで検索継続**（非破壊フォールバック）。固定タグ `[WARN][rewriter_fallback_too_long]` |
| 3 | `config.yml.example` / `docs/CONFIG.md` | `rewriter_max_query_chars: 60` を追記（config.yml は gitignore のため example/docs を更新） |
| 4 | `tests/test_rag.py` | 長文ペルソナ→フォールバック / `[NO_SEARCH]`長文素通り / 通常素通り / answer()経由で検索継続、の4テスト |

### 決定事項
- 閾値60＝正常検索語の実測最長49字＋余裕。**フォールバック先は元のユーザー入力**なので誤検知してもデグレは小（指示語解決が効かなくなるだけ）＝非破壊。閾値は config 可変。
- フォールバック時 trace の `rewritten_query` は元クエリに戻り SQL長さ監視 `length>60` で拾えなくなるため、**監視は固定タグ付き WARN ログの grep へ移行**。chat_trace スキーマ拡張は軽微課題に対し過剰として見送り（YAGNI）。

### 実行結果
- `pytest tests/`：303 passed / 182 skipped（DB系はpostgres未起動でskip・api イメージ内で確認）。

### 次のステップ
- 会話自然化 #67（rewriter応答文バグ #64 と同じレビューで挙がった姉妹issue）の実装が次の候補。

---

## 2026-06-29 — auto memory(#56)実機検証・自家中毒対策(#68)実装/デプロイ・自動承認Issue化(#71)

自動記憶(#56・案C)を検証機で有効化して実データ検証 → **Bot発言が記憶対象に混入する自家中毒(self-poisoning)を発見** → #68 で除去、までを1セッションで実施。

### #56 実機検証
- VM `config.yml` に `rag.auto_memory: {enabled:true, max_chunks:30, max_tokens:800}` を追記し worker 再起動。4ギルドで取り込み→自動抽出を確認（全件 pending 着地・承認するまで回答に出ない）。あいがもいどVRC は永続事実なしで NOOP＝安全側。
- **実データA/B**（実会話 transcript＋`scripts/ab_auto_memory.py`）で 事実再現率 **0%→75%** / 誤事実率 **33%→0%**。合成フィクスチャと同傾向を再現。

### #68 Bot発言の取り込み除外（自家中毒対策）— MAGI 3者(Codex/Aider/codex-fugu)PASS / PR #69
| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/models.py` / `src/collectors/text_channel.py` | RawMessage に is_bot 追加・`_to_raw_message` で `is_bot=msg.author.bot` 取得 |
| 2 | `src/db.py` | `messages.is_bot` 列(冪等ALTER)＋`insert_message`14列化＋後始末ヘルパー5本 |
| 3 | `src/chunker.py` / `src/contextualizer.py` | 取得SQL**両方**に `AND is_bot=0`（context_text 経由の再注入も遮断） |
| 4 | `scripts/migrate_exclude_bots_68.py` | 既存データ後始末（Discord API判定マーク→再ビルド＋Qdrant作り直し→Bot由来記憶却下） |
| 5 | `tests/*`（4ファイル） | is_bot取得/chunker除外/contextualizer除外/ヘルパー（全 **493 passed**・CI緑） |

- 検証機クリーンアップ: Bot/Webhook **14author・1227 messages** を is_bot=1 マーク → 全4ギルド再ビルド（**Qdrant 2225点**・/health 200）。`@moi-rag` への人間の言及は話者が人間なので正しく残存。

### ハマりポイント
- 後始末スクリプトが `run_contextualizer`（内部で `asyncio.run`）を `asyncio.run` 配下から直接呼びクラッシュ（`asyncio.run() cannot be called from a running event loop`）。1ギルド目の再index前に落ち Qdrant 部分欠損 → 同型の同期ロジックで即復旧。恒久修正は `worker._ingest` 同様 `await asyncio.to_thread(...)`（**PR #70**・人間マージ待ち）。

### 決定事項
- **#68（Bot除外）は将来の「①全自動承認」より先に入れる**（MAGI全員合意）。Bot除外なしで自動承認すると自家中毒が自動化するため。
- 新規メッセージは `author.bot` で自動除外＝Bot面はノーメンテ。ただし**抽出は自動でも反映は手動承認のまま**。

### 次のステップ
- PR #70（asyncioバグ修正）を人間マージ。
- **#71（自動記憶の自動承認＋精度ガード）** を起票済み（確信度しきい値/op絞り込み/レート等とセットで段階導入）。Issue #56 のクローズ判断。

---

## 2026-06-28 — ハイブリッド検索(#54)を staging で本番ON＋トレース記録修正(#58)

案A ハイブリッド検索(dense+BM25 sparse/RRF・#54/PR #57)を検証機 remember-vm で有効化した。

- `scripts/migrate_hybrid_reindex.py` で全 2,238 チャンクを dense+sparse で再インデックス
  （collection `waiwai_chunks` の `sparse_config={bm25:{modifier:idf}}` を確認）。
- VM の `config.yml` に `rag.hybrid: {enabled:true, prefetch_k:30}` を手動追記
  （config.yml は gitignore＝`git reset --hard` では入らない既知の落とし穴）→ api/bot/worker を再起動。
- 実機検索で RRF 融合スコアが返ることを確認（cosine ではなくランク融合値）。回答品質は正常。

### トレース記録バグ修正（#58 / PR #59）

| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/db.py` | `chat_trace` に `hybrid_enabled BOOLEAN` 列追加（CREATE TABLE）＋既存DB向け冪等 `ALTER ... ADD COLUMN IF NOT EXISTS`。`insert_trace` に引数追加し INSERT に含める |
| 2 | `tests/test_db.py` | engine の trace 行キーを `insert_trace` がすべて受け付けることを署名契約＋実 `**row` 展開で固定する回帰テスト |
| 3 | `docs/SCHEMA.md` | `hybrid_enabled` 列を追記 |

- 症状: api ログで `/chat` のたび `insert_trace() got an unexpected keyword argument 'hybrid_enabled'` が出て
  トレースが**全件記録失敗**（回答は握り潰し設計のため 200 OK で正常）。
- 原因: #54 マージ時の semantic conflict。engine 側だけ trace 行に `hybrid_enabled` を足し、
  db.py（`insert_trace`）と `chat_trace` テーブル列の対応が抜けていた。テストは `insert_trace` を
  直接 hybrid_enabled 無しで呼ぶため緑のまま、`**row` 経路が未カバーですり抜けた。
- 結果: ローカル(tmpfs Postgres 5433) `test_db`+`test_rag` **169 passed**・CI 緑。

### ハマりポイント
- `Closes #58` は `develop` マージでは自動クローズされず、`gh issue close 58` で手動クローズ。
- #57(hybrid) の自動 deploy は手動 `docker compose up` と競合して failure になったが、
  手動 bringup で実機は #57 コードで正常稼働していた（実害なし）。

---

## 2026-06-24 — #38 API認証対応（/chat・/remember の Bot→API 共有シークレット）

公開/課金前の P0 セキュリティ課題 #38（旧 OI-45）として、`/chat`・`/remember` が無認証で
`guild_id` をクライアント指定できる問題を修正した。PR #50 を `develop` にマージ済み。

| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/api.py` | `ORACLE_API_TOKEN` 設定時に `X-Oracle-Token` を検証し、`/chat`・`/remember` を 401 で保護。`/health` は無認証維持 |
| 2 | `moimoichan_Discordbot/oracle_client.py`・`bot.py` | Bot 側から `ORACLE_API_TOKEN` を読み、API呼び出し時に `X-Oracle-Token` を送信 |
| 3 | `src/cli.py`・`chat_cli.py` | CLI 動作確認時も `ORACLE_API_TOKEN` を送信可能に変更 |
| 4 | `docker-compose.yml` | API/admin のホスト公開を `127.0.0.1` bind に変更し、外部到達を既定で抑止 |
| 5 | `.env.example`・`docs/CONFIG.md`・Bot config example | `ORACLE_API_TOKEN` の運用方法を追記 |
| 6 | `tests/test_api.py`・`tests/test_cli.py` | token 無し/誤 token の 401、正 token 成功、CLI header 送信を検証 |

### 決定事項
- `ORACLE_API_TOKEN` 未設定時はローカル開発・既存テスト互換のため fail-open とする。
- 本番/共有環境では `.env` に長いランダム文字列を設定し、api/bot の両方へ同じ値を渡す。
- `/health` はヘルスチェック用途のため無認証で維持する。

### ハマりポイント
- PR本文の `Closes #38` は `develop` マージでは自動クローズされなかったため、マージ後に `gh issue close 38` で手動クローズした。
- ローカル `develop` は OI移行ドキュメント9コミット分 ahead していたため、#50 マージ分を merge commit で取り込み、まとめて `origin/develop` へ push した。

### 実行結果
- `pytest`: **225 passed, 151 skipped**
- PR: #50 / Issue: #38（クローズ済み）

### 次のステップ
- 次の P0 は #31（Bot退出/purge時の削除範囲不足）。
- `ORACLE_API_TOKEN` を実運用 `.env` に設定し、API/Bot を再起動して認証必須状態で動作確認する。

---

## 2026-06-22 — OI管理を GitHub Issues へハイブリッド移行（採番 #NN・OPEN_ISSUES 1024→94行）

肥大化した `docs/OPEN_ISSUES.md`（1024行/OI 54件・手動採番 `OI-44` が2系統で衝突）を、
GitHub Issues 中心のハイブリッド管理へ移行した。3者レビュー（Claude Code/Codex/Aider 全員PASS）→ プラン承認 → 実装。

| # | ファイル | 内容 |
|---|---|---|
| 1 | `CLAUDE.md` | 採番を `#NN` へ移行（`OI-XX` は OI-54 で凍結）・OPEN_ISSUES の役割変更・「PRは `Closes #NN` で Issue 紐づけ」運用を追記 |
| 2 | `docs/OPEN_ISSUES.md` | インデックス表（OI-XX→#NN）＋確定設計決定＋完了アーカイブへ再構成（**1024→94行**） |
| 3 | `docs/oi_migration.tsv` | OI→Issue 移行マニフェスト（#31〜#47・冪等運用の記録） |
| 4 | `scripts/migrate_oi_to_issues.py` | 一回限りの冪等移行スクリプト（manifest 連動・再実行で重複作成しない） |
| 5 | GitHub Issues | 未着手OIを **17件**起票（#31〜#47） |
| 6 | GitHub Labels | `P0`〜`P3` / `area:*`（6種）/ `kind:*`（3種）を作成 |
| 7 | memory `feedback_read_open_issues` | 参照先に GitHub Issues を追加 |

### 決定事項
- **採番は GitHub Issue の `#NN` を正典**に。独自 `OI-XX` は **OI-54 で凍結**（手動採番の衝突を根絶）。
  コードに深く埋まった既存 `OI-XX`（engine.py 16・bot.py 12・DEVLOG 53 等）は**書き換えず温存**し、
  OPEN_ISSUES のインデックス表で `OI-XX → #NN` を橋渡し。
- 未着手OIは全件 Issue 化。**アイデア群（OI-28〜43）は「魅力強化 epic」#33 に集約**、
  **収益化ロードマップ OI-14 は epic #32**。完了済みOIは OPEN_ISSUES の完了アーカイブに1行で保持。
- **OI-16（コスト最適化）は「ほぼ完了」扱いでアーカイブ**、**OI-17（function calling 見送り）は確定設計決定**として保持。
- 各 Issue 本文に `Legacy-ID: OI-XX` / `Source` を入れ双方向リンク化（Codexレビュー反映）。
- PR運用: PR本文に `Closes #NN` で Issue と紐づけ（マージで自動クローズ・マージは人間）。

### ハマりポイント
- **採番衝突の正体は重複起票**: 旧 `OI-44〜49`（コードレビュー指摘）は `OI-44〜51`（codex-fugu 安全性レビュー）と
  同一内容だった。Issue化の際に統合（片方のみ起票・統合理由を本文に明記）。
- 既存PR等で番号が消費済みのため、**新規 Issue は #31 から**採番された。

### 次のステップ
- 人間が develop を push（本セッションのコミット5件: `2fc64a2`〜`dd4f1b5`）。
- 今後の課題着手は GitHub Issues 起点で。最優先は P0（#31 purge範囲 / #38 API認証）。

## 2026-06-20 — CD導入: develop マージで remember-vm へ自動デプロイ（PR #29）

CIに続きCDを導入。`develop` への push（PRマージ）で pytest 緑→検証機 `remember-vm` へ自動デプロイされる。

### 方式選定
- **self-hosted runner（pull型）を採用**。VMはTailnet限定（インバウンド）でGitHubホストrunnerから到達不可だが、
  runnerはVMから外向きにGitHubへロングポール接続するため成立。SSH鍵・Tailscale越え・GCP認証をCIに置かずに済む。
- 対抗案（GitHubホスト+Tailscale action+SSH push）は新規シークレットが多く不採用。

### 実装（[.github/workflows/tests.yml](../.github/workflows/tests.yml) に `deploy` ジョブ追加）
- `needs: pytest` / `if: push && ref==develop` / `runs-on: [self-hosted, remember-vm]` / `concurrency` で直列化。
- ステップ: `~/remember` で `git reset --hard origin/develop` → `docker compose up -d --build` → `/health` 200確認。
- `.env`/`config.yml`/`data/` は .gitignore 済みで `reset --hard` でも保持される（追跡ファイルにコード手編集が無いことを事前差分確認）。

### VM側セットアップ（一回限り・SSH代行で実施）
- `~/remember` は tarball展開のままでgit未初期化だったため **git化**（`git init`→develop に reset）。
- 認証は **read-only SSHデプロイキー**（`~/.ssh/remember_deploy`・`gh api .../keys` で登録）。
  当初PATを `.git/config` 直書きしようとしてハーネスに静止され、より安全なデプロイキーへ切替（PATは失効）。
- runner v2.335.1 を **systemdサービスとして常駐化**（`svc.sh install`・passwordless sudo確認済み・label `remember-vm`）。
- VMのoutboundは443/22とも開通済みを実測（Tailscale制限はインバウンドのみ）。

### 検証
- マージ前にデプロイ手順をVM上で手動実行 → 再ビルド34秒・`/health` 200・postgres/qdrant無停止を確認。
- マージ後の初の自動デプロイ run を観察 → `pytest 59s` / `deploy 51s` 両方success、VM HEAD=PR#29マージ・`/health` 200。

### 運用メモ
- VM自動停止（JST 2/9/17時）中にマージしてもジョブはキュー待機→起動時に自動実行。
- デプロイ失敗時は赤化し旧コンテナ継続＝稼働中サービスは保護される。
- CDの恒久運用ルールは CLAUDE.md「CI/CD」セクションに反映済み。

## 2026-06-19 — 明示メモリ機能(OI-24) 読み書き実装・A/B・VM動作確認

ユーザーが「◯◯は△△だよ、覚えておいて」と教えた**事実**を、Discord過去ログとは別の記憶領域
（`memories`テーブル）に保持し、回答プロンプトへ注入する機能。読み取り→効果A/B→書き込み→抽出A/B
→検証機デプロイ→本番動作確認まで一気通貫で実施（PR #27）。

### やったこと
| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/db.py` | `memories`テーブル＋`insert_memory`/`fetch_memories`/`delete_memory`/`count_memories`（全guild_id分離） |
| 2 | `src/memory.py` | `MemoryProvider`（guildの教わった事実を読む callable・TraceRecorder流儀） |
| 3 | `src/rag/prompts.py` | `MEMORY_SECTION`＋`build_memories`（読み）/ `MEMORY_EXTRACT_PROMPT`（書き・JSON抽出） |
| 4 | `src/rag/engine.py` | `answer()`にメモリ注入 / `extract_memory()`（LLMでsubject/content抽出・null判定） |
| 5 | `src/api.py` | `POST /remember`＋`memory_saver`（テスタブル化）/ `build_engine`で`memory_provider`配線 |
| 6 | `moimoichan_Discordbot/bot.py`・`oracle_client.py` | メンション＋フレーズ検知→`/remember`→「覚えたよ！」返信 |
| 7 | `config.yml.example`・bot config | `rag.memory_enabled`（既定OFF）/ `oracle.remember_phrases` |
| 8 | `tests/`・`scripts/` | テスト+約30件 / 使い捨てA/B `ab_memory.py`・`ab_memory_extract.py` |

### A/B結果
- **読み取り（注入あり/なし）**: 記憶系 1.00→**5.00**、対照系 4.67→**5.00**（幻覚も矯正・脱線なし）。
- **書き込み（LLM抽出 vs 素朴保存）**: SHOULD抽出 **5.00** vs 2.00、NOISE誤爆 **0/4** vs 4/4。LLM抽出採用。

### ハマりポイント
- **semantic conflict（CI赤）**: 作業中に develop へ OI-23 検索ゲート(PR #26)がマージされ、PR CIは
  「develop+feature」で回るため、検索スキップ時に`SKIP_CONTEXT`でなく`build_context(hits)`で上書き
  していた箇所が衝突。`develop`を取り込み`{context}`変数を使う形で解消→356 passed→force-with-lease。
- **VMで覚えない**: 原因は VM実`config.yml`に`memory_enabled`が無く既定OFF。検知・配線・コードは正常
  （`POST /remember 200`がログにあった）。`config.yml.example`だけ更新し実configを更新し忘れていた。

### 決定事項
- 保存先は**Postgres全件注入**（少数前提・件数増でQdrant化を再検討）。書き込みはLLM抽出（誤爆制御が決定的に優位）。
- 分離は**guild単位**（guild内は全員共有・user分離はしない＝過去ログRAGと同じ仕様）。

### 検証機での本番動作確認
- VMに`memory_enabled: true`追加＋`restart api bot`→ Discordで実テスト→ `memories`に4件保存を確認。
- 読み取りも `chat_trace` で確認（「ほしのかなた」質問に保存済み「低学歴」が回答へ注入）。

### 次のステップ
- **センシティブ属性ガードレール**（OI-25候補）: 「低学歴」等の中傷的属性が保存・発話された。公開前に必須。
- 後段: `/oracle forget`・admin CRUD・更新vs追記の上書き戦略・件数増でのQdrant化・個人メモリ分離。

---

## 2026-06-19 — デバッグトレース(OI-21)・プロンプトv4・リランカーA/B

「精度が落ちた・以前の方が良かった」という所感を起点に、観測性→診断→改善まで一気通貫で対応した。

### やったこと
| # | 内容 | PR |
|---|---|---|
| 1 | **OI-21 デバッグトレース**: `chat_trace` テーブル＋`src/trace.py TraceRecorder`。1回の `/chat`（質問/書き換え/ヒットチャンク本文/回答/トークン/コスト/レイテンシ）を1行で保存。`config.yml rag.debug_trace`（既定OFF・プライバシー）。テスト+10 | #20 |
| 2 | **.dockerignore 追加**（`data/` 等を除外） | #21 |
| 3 | **プロンプトv4**: れみの口調は維持し情報量を回復（「曖昧に/短く」撤廃・ランキング等の依頼にも応じる） | #22 |
| 4 | **.dockerignore バグ修正**（行末コメントで `data/` 除外が効かずビルドが落ちていた） | #23 |

### 診断と検証（chat_traceが効いた）
- **質問ログが無かった**ためA/Bの質問すら実チャンクから推測する羽目に → OI-21で穴を埋めた。
- **プロンプトA/B**（`scripts/ab_prompt_test.py`・chat_traceの同一検索結果で回答だけ差し替え）で
  v3 vs v4 を比較 → v4が明確に改善（「優しい人ランキング」: v3拒否→v4具体的に5人列挙 等）。所感を実証。
- **リランカーA/B**（`scripts/ab_rerank_test.py`・実テスト鯖・5問）→ **明確な改善なし・むしろ悪化例あり**。
  Jina v2 は費用対効果が見合わず**本番有効化は見送り**（既定OFF維持）。詳細は OPEN_ISSUES OI-9。

### デプロイ（remember-vm・検証機）
- develop tarball をクリーン展開＋設定/データ保持で再デプロイ。**debug_trace: true** で運用（実トレース収集）。
- ハマり: `.dockerignore` の**行末コメントは非対応**（`data/ # …` がパターン化して除外が無効）→ ビルドが
  `data/postgres: permission denied` で落ちた。コメントは行頭のみに修正（#23）。

### 決定事項
- 回答品質の主レバーは**プロンプト**（retrievalは概ね良好）。リランカーは現状不採用。
- センシティブ属性（性的指向・健康等）の実名ランキングは v4 が答えるようになった → **公開前に OI-14 A（法務）で
  ガードレール方針を決める**（今回は検証機優先で見送り）。

## 2026-06-19 — CI（GitHub Actions）導入・docs直接コミット運用・メインdir develop化

PR作成時の自動テストが無く手動 `pytest` だった状態を解消し、CI を導入。
あわせて運用ルール（ドキュメントのコミット方法・worktree整理）を整備した。

| # | ファイル | 内容 |
|---|---|---|
| 1 | `.github/workflows/tests.yml` | **新規**。PR/push(main,develop)時に pytest 自動実行。Postgresはサービスコンテナ(`postgres:16`)・`TEST_DATABASE_URL`で接続。Python 3.11（PR #14でdevelopにマージ） |
| 2 | `tests/test_api.py` | TestQuotaの期待タプルを4→5要素に修正（`engine.answer`のhistory引数追加に追従・develop赤を解消／PR #18） |
| 3 | `CLAUDE.md` | CIセクション追記＋「docsはPR不要でdevelop直接コミット可」「semantic conflict注意」を明文化（PR #17・以降はdevelop直接） |
| 4 | `docs/ARCHITECTURE.md` | ディレクトリ構成に `.github/workflows/tests.yml` を追記 |
| 5 | `docs/DEVLOG.md` | remember-vmデプロイ記録の取り込み＋本エントリ |

### ハマりポイント
- **semantic conflict**: 古いfeatureブランチ(oi14)が、共有関数のシグネチャ変更後のdevelopにマージされ、**テキスト衝突なしにテストが壊れた**。CI導入初日に検知できたのが収穫。
- `.github/workflows/` のpushには gh トークンの `workflow` スコープが必要（`gh auth refresh -s workflow` でブラウザ認可）。
- PR CIは「head＋最新developのマージ結果」で走るため、developが赤いと無関係なdocs PRも赤くなる（developを先に直すのが正解）。
- `~/Desktop` 配下のiCloud同期が worktree に「 2」複製ゴミ（`.git 2`等）を量産。worktree運用と相性が悪く要注意。

### 決定事項
- **ドキュメント（CLAUDE.md/DEVLOG等）はPR不要でdevelopへ直接コミット**（gitignoreはしない＝共有維持）。コードは従来どおりfeatureブランチ＋PR。
- **PRのマージは人間が行う**（Claude CodeはPR作成まで）。
- **メイン作業dirは develop に固定**（クリーンな統合基点・他セッションの方針に合わせた）。別ブランチ作業はworktreeで分離。
- 未コミットだったREADME書き直しは develop(`b78f623`)で対応済み＝重複のため不採用、AGENTS.md(旧コピー)は有害につき破棄。

### 次のステップ
- `~/Desktop` をクラウド同期対象から外す等、worktree運用の安全化を検討。
- 将来CD（GCP VMへの自動デプロイ）の検討（今回はCIのみ）。

## 2026-06-18 — develop (`d2274a8`) を remember-vm に反映

OI-18 マージ済みの `origin/develop` を GCP 検証機 `remember-vm` にデプロイ。  
※`feature/oi18-mention-resolution` は既に PR #9 で develop にマージ済みであったため、新たな push/PR は不要だった。

### 作業手順
- ローカルで `git fetch origin develop` → `git archive origin/develop` で tarball 化（`.env`/`config.yml`/`data/` は除く）。
- Tailscale SSH (`aigamoid@100.98.83.15`) 経由で `/tmp/remember-develop.tar.gz` を転送。
- VM 上で既存 `~/remember` を `~/remember-old-20260617-154339` にリネームしてバックアップ。
- クリーンに tarball を展開し、以下を旧ディレクトリから移動/コピーして設定・データを保持：
  - `.env`、`config.yml`、`moimoichan_Discordbot/config.yml` を `cp`
  - `data/` は `sudo mv`（Postgres ユーザー所有のまま権限保持）。
- `docker compose up -d --build` で 6 サービスを再ビルド＆起動。

### 保持した運用設定
- VM の `config.yml` は OI-16 最適化（`answer_model: deepseek/deepseek-v3.2`、`top_k: 5`、`answer_max_tokens: 1500`）のまま。
- `history_max_turns` など OI-10 の新キーは存在しないため、コードのデフォルト値（履歴有効）で動作。

### 動作確認
- API `/health` → `200 OK`
- Admin `/login` → `200 OK`
- Bot → `Shard ID None has connected to Gateway`
- Discord からの `POST /chat` → 複数回 `200 OK`
- `docker compose logs` 全体で `ERROR`/`Exception`/`Traceback` なし
- Qdrant クライアントバージョン差の `UserWarning` は非致命。

### 備考
- 旧ディレクトリ `~/remember-old-20260617-154339` は削除前に問題ないか確認中。
- 次回以降のデプロイも同様に tarball 転送＋クリーン展開＋設定保持で運用する。

## 2026-06-18 — OI-15 れみちゃんリブランド引き継ぎ ＋ PRマージ運用ルール

OpenCodeが実装した OI-15（回答キャラのリブランド）を Claude Code が引き継いでマージし、
あわせて「PRのマージは人間が行う」運用ルールを整備した。

### 変更ファイル
| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/rag/prompts.py` ほか | OI-15: 回答キャラ「わいわいちゃん→れみちゃん」（ゆるふわ・友達口調）。OpenCode実装 |
| 2 | `config.yml.example` | OI-15: `guild_name` デフォルト→「みんなのサーバー」（OI-9 rerankerブロックと両立解決） |
| 3 | `prompts/v3_remi_rebrand.md` ほか | プロンプト履歴 v3 追加・README/docs併記更新 |
| 4 | `CLAUDE.md` | **PRのマージは人間が行う（Claude CodeはPR作成まで・`gh pr merge`しない）** を明記（PR #16） |

### 決定事項
- **PRのマージは必ず人間**（push と同じ精神）。「マージまでやって」でも最終マージは人間に渡す。
  メモリ `feedback_pr_merge_policy.md` ＋ CLAUDE.md に記録。
- 旧develop基点のブランチは**最新developへrebase**してから出す（OI-15は衝突1件=config.yml.exampleを両立解決）。

### ハマりポイント
- OI-15を一度誤って `gh pr merge` → develop から **revert** → 新コミットでPR再作成 → ユーザーがレビューしてマージ。
  この反省から上記ルールを策定。
- 並行セッション（Claude Code/OpenCode）が同一 develop に短時間で複数マージ → revert が後続マージで打ち消される等、
  混線が起きやすい。worktree分離＋人間マージで収束。

### 次のステップ
- VM復元後に**リランク品質A/B（大データ）**→本番有効化判断（OI-9）。
- 脱waiwaiの残リネーム（リポジトリ名 / `/oracle` / `waiwai_chunks` / `moimoichan_Discordbot/`）。

---

## 2026-06-18 — OI-14 C-2: プラン上限(quota) ＋ プラン管理 ＋ 課金ポータル（PR #15）

収益化の青天井を止める **C-2** を `feature/oi14-c2-quota` で実装、develop へマージ済み（PR #15）。
プラン定義はDB管理でポータルから編集可能。回答挙動は上限内では不変。

### 料金プラン（確定）
| プラン | 月額 | 取り込みch | 質問/日 |
|---|---|---|---|
| Free | ¥0 | 1 | 20 |
| Pro | ¥700 | 10 | 80 |
| MAX | ¥1500 | 無制限 | 200 |

超過時は全プラン **ハードストップ＋翌日(JST 0時)リセット＋アップグレード案内**。
実測コスト≈¥0.2/問(OI-16後)なので満杯でも赤字にならない。相場($5〜$20/サーバー)内。

### 変更ファイル
| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/db.py` | `plan_defs`/`guild_plans` テーブル・`seed_plans`・CRUD・quota集計（`count_questions_since` 等） |
| 2 | `src/quota.py`(新) | JST日次境界・上限判定・案内文（純ロジック） |
| 3 | `src/api.py` | `/chat` 入口で日次質問上限を判定→超過は回答せず案内（コスト0）・DB障害はfail-open |
| 4 | `moimoichan_Discordbot/store.py`・`bot.py` | `/oracle allow` でチャンネル数上限を強制 |
| 5 | `src/admin/app.py`＋`billing.html` | `/billing`: プラン定義編集＋サーバー割当＋本日の消化 |
| 6 | tests（quota/db_plans/api）＋conftest | 新規37件。フルスイート **282 PASS** |
| 7 | docs(SCHEMA/ARCHITECTURE/OPEN_ISSUES) | C-2反映 |

### 決定事項
- **プラン定義はハードコードせずDB(`plan_defs`)管理**＝ポータルから即時変更（再デプロイ不要）。
- サーバー割当 `guild_plans`（無い=free）。**Stripe列を予約**し、プラン自動切替は OI-14 D で接続。
- 上限超過の挙動は**全プランA（ハードストップ＋翌日リセット＋案内）**。
- 質問上限＝API入口・チャンネル上限＝Bot allow。日次境界は **JST 0時**。

### ハマりポイント（環境・C-2とは別件）
- ローカル colima/virtiofs 上の compose postgres で pytest が
  `InsufficientPrivilege: could not open file ... Permission denied` を非決定的に頻発
  （**変更なしのベースラインでも86エラー**＝virtiofsでPostgresがファイルを開く際の権限揺らぎ）。
- 対処: **tmpfsの使い捨てPostgres(5433)** でテスト → 安定して 282 PASS・約4倍速(2-3秒)。
  committed compose は変更せず（GCP/Linuxは問題なし）。手順はメモリ `feedback_test_db_tmpfs` に記録。

### 次のステップ
- OI-14 D（Stripe課金）: 入金→Webhookで `guild_plans` 自動更新（C-2のフラグ手動運用を自動化）。
- A（法務）仕上げ（プレースホルダ確定・公開先決定）。
- develop → main のリリース整理（main は別ルートの空のため要対応）。

## 2026-06-17 — OI-10/OI-20: マルチターン会話履歴 ＋ 回答プロンプトへの現在日時注入

回答が「今日」を過去ログ内の日付（例: 5/6）と誤認するバグ（OI-20）を直し、ついでに
ずっと未対応だったマルチターン会話（OI-10）を実装した。同ブランチ
`feature/oi10-multiturn-history`。

### きっかけ（OI-20 のバグ）
「今日は何の予定？」的な質問で、過去ログの「5/6に集合ね！」がヒットし、**実日付（6/17）でなく
5/6 を「今日」として回答**していた。調査すると `REWRITER_SYSTEM_PROMPT` には現在日時が
注入されていたのに、**回答プロンプト `ANSWER_SYSTEM_PROMPT` には現在日時が一切無かった**
（`engine.answer()` は guild_name と context しか差し込んでいなかった）。回答LLMは「今」を
知らず、日付付きチャンクの過去/現在を判断できなかった。

### OI-20 の修正（現在日時注入）
- `src/rag/prompts.py`: `ANSWER_SYSTEM_PROMPT` に `## 現在時刻`（`{current_datetime}`）を追加。
  「記憶の断片はすべて過去の記録／相対表現・予定は記憶内の日付でなく現在時刻基準で判断」と明記。
- `src/rag/engine.py`: `answer()` で `_now_str()` を差し込む。

### OI-10 の実装（マルチターン会話履歴・ステートレス設計）
APIはステートレスのまま、**呼び出し側（Bot/CLI）が直近会話を保持して毎回 history を渡す**方式。
- `src/rag/llm.py`: `complete()` に `history` 追加。messages を `system → history → user` で構築。
- `src/rag/engine.py`: `answer()`/`rewrite()` に `history`。`_prep_history()` で検証＋直近
  `rag.history_max_turns` ペアに丸める。**Rewriter にも history を渡す**ので「それ」「さっきの件」
  の指示語解決も効く（Rewriter プロンプトのルール2 が初めて機能する）。
- `src/api.py`: `ChatRequest.history` を追加し素通し。
- `moimoichan_Discordbot/bot.py`: **チャンネル単位** deque で直近やり取りを保持（1ch＝1会話）。
  成功時のみ追記。`oracle_client.py` が history を送信。
- `chat_cli.py`: REPL が履歴保持（`reset` でクリア）。CLIでマルチターンの動作確認が可能。
- 設定: `rag.history_max_turns`（既定5・0で無効）／ bot config `oracle.history_max_turns`。

### テスト・反映
- テスト +14件（会話履歴・現在日時注入・messages組み立て・履歴バジェット）。全 **266 PASS**（Mac・worktree）。
- 反映には api 再ビルドが必要（`docker compose up -d --build api`）。Bot も再起動。
- 履歴は非永続（Bot/CLI のメモリ上のみ・再起動で消える）。

### A/B検証（ローカル31チャンク）と本データでのコスト計測（VM 1,100チャンクをローカルへコピー）
- **精度（OI-20/OI-10）**: 「今日は何日？」→ 旧:答えられない / 新:2026-06-17。「Moltbook制限は今解除？」→
  旧:2月を"今"と誤認し「まだ停止中かも」/ 新:「現在6/17なのでとっくに解除済み」。指示語「それ」を含む
  2ターン目 → 旧:全く別話題を回答 / 新:文脈を保持。**報告の日付誤認バグの再現→解消を確認**。
- **5ペア履歴のコスト（同一質問を履歴0 vs 5ペアで計測・deepseek-v3.2）**:
  - 履歴0: 入力4,348tok / **$0.00130**　→　履歴5ペア: 入力9,633tok / **$0.00325**（約2.5倍・+$0.00195/問）。
  - 内訳: answer入力 +2,783tok、**rewrite入力 +2,039tok**（履歴はrewriterにも乗り二重計上）。
  - 絶対額は安いが、`answer_max_tokens=1500` のため最悪時は履歴だけで~7,500tok×2になり得る。

### 追加対応: 履歴のトークン（文字数）バジェット制御（上記コスト計測を受けて）
- `_prep_history(history, max_turns, max_chars)` に**文字数バジェット**を追加（ペア数で丸めた後、
  合計が `history_max_chars` 以内に収まるよう古いメッセージから落とす）。
- **回答LLM向け（広め）と Query Rewriter 向け（狭め）で別々に整形**。rewriter は
  `rewriter_history_max_turns`(既定2)・`rewriter_history_max_chars`(既定1000) でさらに絞り、
  指示語解決に必要な最小限だけ渡して token 二重計上を抑える。
- 新config: `rag.history_max_chars`(4000) / `rag.rewriter_history_max_turns`(2) /
  `rag.rewriter_history_max_chars`(1000)。`history_max_turns=0` は両方を完全無効化。

---

## 2026-06-17 — OI-9 Phase1: リランカー導入（feature/oi9-reranker）

検索品質を上げるため、dense検索の後段に **cross-encoder リランカー**（Jina API）を追加した。
方式は「dense で多め(top_n=30)に取って top_k に精選」（Direction A）。

### なぜ Direction A（リランカー）を先に
- 日本語に強い（多言語cross-encoder）。BM25ハイブリッドは日本語分かち書きが弱い。
- **既存データの再インデックス不要**（dense indexのまま後段で並べ替えるだけ）。
- 「多く取って絞る」が OI-16 のコスト方針と噛み合う。

### 変更（worktree運用・1ファイル1コミット）
- `src/rag/reranker.py`（新規）: Jina Reranker クライアント（httpx）。`RerankResult{order, total_tokens}`。
  キー未設定/失敗は例外 → 呼び出し側でフォールバック。
- `src/rag/engine.py`: `rag.reranker.enabled` 時のみ dense `top_n`→リランク→`top_k`。
  失敗時は dense順にフォールバック（回答は止めない）。usage_log に `rerank` を記録（reranker.model）。
- `src/api.py`: `build_engine` で enabled 時に Reranker を生成して注入（キーは `JINA_API_KEY`）。
- `config.yml.example` / `docs/CONFIG.md`: `rag.reranker`（enabled/provider/model/top_n）＋pricing追加。
- `.env.example`: `JINA_API_KEY`。
- tests: `test_reranker.py`（httpx MockTransportでJina模擬）＋ `test_rag.py` に TestRerank
  （並べ替え/候補多取り→top_k/無効時不呼出/失敗フォールバック/usage記録）。

### 決定・安全策
- **既定オフ**（`enabled: false`）。キー無しでも既存動作は不変。有効化は config＋`JINA_API_KEY`。
- リランカーは engine に注入する設計（テストは FakeReranker でAPI不要）。

### テスト
- リランカー＋RAGエンジン: **34 PASS**。全体は 258 PASS。
- ※DB系テストで `InsufficientPrivilege` が散発したが、これは**複数worktreeが同一ローカル
  `oracle_test` DBを同時に使う競合**（環境要因・OI-9とは無関係）。単独実行では全て通る。

### 残・次
- 実データで品質A/B（top_n・top_k 調整）と pricing 実値更新 → 本番有効化の判断。
- 足りなければ Phase2（BM25ハイブリッド）を再検討。
- 別件: テストDBのworktree間競合は要対処（DB名をworktreeごとに分ける等）。

---

## 2026-06-17 — OI-16: 回答1メッセージのコスト最適化（Mac＋GCP検証機に反映）

1問あたり実測 ≈ $0.016 だった回答コストを、品質を保ったまま **約1/5（$0.0032）** まで削減した。

### 変更（バランス案）
- `config.yml rag.top_k` 10→5（回答 context をほぼ半減・最大のレバー）。
- `config.yml rag.answer_max_tokens: 1500` 新設＋`src/rag/engine.py` の answer 呼び出しに `max_tokens` を渡す
  （completion の暴走を防ぐ安全弁）。
- `config.yml rag.answer_model` を Kimi K2 → **DeepSeek V3.2** に変更。`pricing` も OpenRouter 実価格へ更新。
- `scripts/ab_cost_test.py` 追加（同一質問・同一検索結果で複数モデルのコスト/回答を並べて比較する手動計測）。

### A/B計測（同一context・top_k=5・2問）
- Kimi K2: $0.0058 / $0.0094（平均 ≈ $0.0076/問）
- DeepSeek V3.2: $0.0017 / $0.0029（平均 ≈ $0.0023/問・約1/3）。
  キャラ語尾「！っ」・絵文字・Markdown構造も維持で品質劣化なし。

### GCP検証機への反映・実機検証
- `config.yml` は gitignore のため、Mac版 `config.yml`＋`src/rag/engine.py` を VM(`remember-vm`) へ scp 転送し
  `docker compose up -d --build`（転送前に VM の config.yml と diff し差分が今回の4点のみ＝VM固有値なしを確認）。
- VM の `usage_log` で before/after を実証: **kimi-k2 $0.01625（25,915 tok）→ deepseek-v3.2 $0.00315（12,572 tok）＝約1/5**。
- 別サーバー（9,728メッセージ）の取り込みテストも実施し、全ジョブ done・chunk_index=Qdrantベクトル数が一致＝整合OK。

### 副産物
- `わいわい本番Discordサーバーは検証でも使用禁止・データは検証用に残置OK` という方針を確認（メモリ記録）。
- worker に無害な `RuntimeError: Event loop is closed`（httpx 後始末ログ）が散発 → **OI-19** として既知事項に記録。
  根本対応（非同期クライアント明示クローズ）は検証一段落後に。

---

## 2026-06-16 — OI-18: `<@ID>` メンションの表示名解決（feature/oi18-mention-resolution）

回答に出る `<@123...>` を「誰の発言か」分かるよう **`@表示名` に決定論的に解決**した。
LLMツール使用（OI-17）に頼らず低コスト・低リスクで品質を上げる狙い。

### 方式の決定
- **取り込み時に解決して chunk_text に保存**を採用（回答時の追加処理ゼロ＝OI-16のコスト方針と整合）。
  回答時に毎回置換する案もあったが、エンジンをDBに結合させずに済む取り込み時方式を選んだ。
- 名前のソースは messages テーブルの `author_id→author_name`（過去に発言した人をカバー）。
  同一IDで改名があれば最新を採用（`DISTINCT ON ... ORDER BY timestamp DESC`）。

### 変更（1ファイル1コミット・計7）
- `src/formatter.py`: `resolve_mentions()` ＋ `format_message_line(mention_map=...)`。
  `<@ID>`/`<@!ID>`→`@名前`、未知IDは原文維持、ロール/チャンネルmentionは対象外。
- `src/db.py`: `fetch_mention_map(conn, guild_id)`。
- `src/chunker.py` / `src/contextualizer.py`: map を一度構築し chunk_text・preceding を解決。
- tests: `test_formatter.py`（新規）＋ `test_db`/`test_chunker` に追加（+13件、計 **253 PASS**）。

### 効果・確認
- 既存データの **7.3%（614/8395チャンク）** が生 `<@ID>` を含むと実測（読み取りのみ）。
- 統合テストで run_chunker 後の chunk_text に `@表示名` が入り `<@ID>` が消えることを検証。

### 残
- 既存チャンクは次回syncの再取り込みで自然反映（即時反映は手動re-chunk＝再embeddingコスト）。
- lurker（未発言ユーザー）の `<@ID>` は未解決のまま。必要なら将来 Discord REST 補完。

---

## 2026-06-15 — GCP移行（lift-and-shift・検証機/ステージング）完了

OI-14 E。オンプレ（Mac）から GCP の単一VMへ lift-and-shift で移行。**初心者向け・セキュア
（Tailscale経由・公開インバウンド0）**を方針に、Phase 0〜3 を完走し**6サービス本番稼働＋
RAGエンドツーエンド動作**を実機確認。このVMは現状ステージング、後に本番化予定。

### 実施内容（Phase別）

| Phase | 内容 |
|---|---|
| 0 | gcloud CLI導入・認証 / プロジェクト `remember-beta-2606812` 作成・請求紐付け / **予算アラート¥3,000(≈$20)** |
| 1 | VM `remember-vm`（e2-small/asia-northeast1-a/Debian12/30GB）作成 / 自動停止スケジュール JST 2,9,17時 |
| 2 | Tailscale参加（VM=100.98.83.15）/ 公開SSH(22)を**IAP範囲限定**・RDP削除＝**公開インバウンド0** |
| 3 | Docker+compose+swap2G（`scripts/vm_setup.sh`）/ コードをtarball転送(Private repoのため) / 設定3ファイル転送(.env 600) / **6サービス起動** |

### 決定事項
- 構成: **単一VM(lift-and-shift)**。Postgres/Qdrant分離は予算超過のため見送り、コードは
  `DATABASE_URL`/`QDRANT_URL` で疎結合なので後から剥離可能（Phase 6）。
- アクセス2系統: **あなた=Tailscale SSH** / **自動操作=IAP**（`gcloud ... --tunnel-through-iap`）。
- データは移行せず**新規取り込みで開始**（waiwai旧データは不使用方針）。
- 自動停止は**残す**（コスト保険・使う時だけ起動）。Bot稼働はVM1箇所のみ（Mac側は停止維持）。
- 開発はMacローカル、GCPは検証機→後に本番（[[feedback-dev-on-mac]] 相当をメモリ化）。

### 実行結果（実機・GCP上）
- 取り込み: テストサーバーで `/oracle allow` → job done（crawled=241 / chunks=9 / contexts=9 / indexed=9）。
  Postgres 241msg・indexed 9・Qdrant points 9 で三者整合。
- 回答: @メンション質問 → `POST /chat 200` ×2、`usage_log` に rewrite/embedding/answer を実user_id付きで記録。
- **実測コスト: 1問 ≈ $0.016（≈¥2.5）**・answer約26kトークンが支配的 → 概算の3〜16倍。**OI-16** に最適化課題を記録。

### ハマりポイント
- 予算作成が `INVALID_ARGUMENT` → 請求アカウントが**JPY建て**のため `20USD`不可。`3000JPY`で解決。
- VM作成前に **Compute Engine API有効化**が必要 / 自動停止は**サービスエージェントへのIAM付与**が無いと実行されない（runbookに反映済み）。
- Private repo のため git clone せず Mac→VM へ tarball 転送（data/.git/.venv除外、設定ファイルは同梱）。

### 次のステップ
- OI-16: 1問コスト最適化（まず `top_k` 10→5 を usage_log で before/after 計測）。
- Phase 5: バックアップ(スナップショット)自動化・監視 / `.env`→Secret Manager。
- 後に本番機へ移行（現状ステージング）。Phase 6 マネージド化(Cloud SQL/Run)。

## 2026-06-15 — 利用量計測(OI-14 C-1) ＋ 管理ポータル(codename: remember)

収益化ロードマップ OI-14 の **C-1（利用量計測）** と、追加要望の **管理ポータル** を
`feature/usage-metering-portal` で実装し PR #7 を作成（base: feature/multitenant-ingest）。
回答の挙動は不変（計測は副作用なし・DB障害でも /chat は止まらない設計）。

### 変更ファイル

| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/db.py` | `usage_log` テーブル新設・`insert_usage`・ポータル用集計（`fetch_guilds_overview`/`fetch_recent_jobs`/`fetch_usage_summary`） |
| 2 | `config.yml(.example)` | `pricing` 単価表（USD/100万トークン）追加 |
| 3 | `src/usage.py`（新規） | コスト算出 `compute_cost` ＋ `UsageRecorder`（記録失敗は握りつぶす） |
| 4 | `src/rag/llm.py` | `complete()` が `Completion`（本文＋usage）を返すよう変更 |
| 5 | `src/embedder.py` | `embed_one_with_usage` 追加（クエリembeddingのトークン取得） |
| 6 | `src/rag/engine.py` | rewrite/embedding/answer の usage を集約して recorder へ・`user_id` 対応 |
| 7 | `src/api.py` | recorder 配線・`user`→user_id 抽出・起動時スキーマ初期化 |
| 8 | `src/admin/`（新規） | FastAPI+Jinja2 ポータル（`app.py`/`auth.py`/templates 4枚） |
| 9 | `docker-compose.yml` | `admin` サービス追加(8001)・`api` に DATABASE_URL/depends 追加 |
| 10 | `requirements.txt` | `jinja2`・`python-multipart` 追加 |
| 11 | `.env.example` | `ADMIN_PASSWORD`・`ADMIN_SESSION_SECRET` 追加 |
| 12 | `scripts/check_docs.py` | 探索ディレクトリに `src/admin` 追加 |
| 13 | tests/（6ファイル） | usage計測・admin認証/ログイン・DB集計・embedder のテスト追加/更新 |
| 14 | docs/・CLAUDE.md | SCHEMA/ARCHITECTURE/CONFIG/OPEN_ISSUES/CLAUDE を更新 |
| 15 | `src/admin/*`・CLAUDE.md | ポータル表示名を codename **remember** に統一 |

### 決定事項

- **認証**: 管理ポータルは簡易パスワード（`ADMIN_PASSWORD`・HMAC署名Cookie・stdlibのみ）。
- **公開面**: 公開API(/chat)と分離した別 compose サービス `admin`（ポート8001）。
- **集計単位**: guild_id に加え **user_id も記録**（将来のユーザー別分析に備える）。
- **改名スコープ**: 今回は**ポータル表示名のみ** `waiwai-oracle`→`remember`。全体改名は段階実施
  （Qdrantコレクション `waiwai_chunks` はデータ移行が絡むため別途）。「わいわい」(テナント名)・
  「わいわいちゃん」(Botキャラ)は別概念で改名対象外。CLAUDE.md 冒頭に明記。

### 実行結果

- pytest **240件 PASS** / `scripts/check_docs.py` 問題なし。
- 実機: `docker compose up -d --build` → ログイン(301301)→ダッシュボード描画OK。
  テストサーバーへ `/chat` 1回で `usage_log` に rewrite/embedding/answer の3行が記録
  （user_id=u999・answer ≈ $0.0012）。**わいわいサーバーは不使用**。
- データ補正: 移行由来で `left_at` が NULL のままだった「わいわい」guilds行を退出済みに更新
  （ポータルで在籍誤表示していたため。チャンク8,364件は保持・purgeなし）。

### ハマりポイント

- `complete()` の戻り値型変更がテストのフェイクに波及 → `Completion` を返すフェイクに更新して吸収。
- ポータルの「在籍中」は `guilds.left_at IS NULL` のみで判定。移行・手動投入の行は実態とズレ得る
  （真の在籍は Discord ゲートウェイ）。将来 bot.guilds との突き合わせ補正を検討。

### 次のステップ

- C-2（quota/上限）: C-1 のデータを見て料金プラン決定後に着手。
- pricing 単価を最新の OpenRouter/OpenAI 価格に更新。
- プロジェクト全体の `remember` 改名（compose/Qdrant等）。
- ポータルの公開可否（VPN内限定 or 公開＋HTTPS/認証強化）。

---

## 2026-06-15 — 実機E2E完走（OI-12）＋ Query Rewriter修正

ステップ2（feature/multitenant-ingest）の実機E2Eを、テスト用Discordサーバー
「もいもいAI砂場」で実施し完走した。waiwaiサーバーは使用していない。

### E2E結果（全シナリオ想定通り）

| シナリオ | 結果 |
|---|---|
| Bot招待 → `/oracle allow #一般` | ジョブ投入→自動クロール→チャンク→文脈付与→Qdrant登録 |
| 取り込み結果 | 511msg→30チャンク→30ベクトル（guild_id分離をQdrant/PGで確認） |
| @メンション質問 | 実ログ準拠の回答（Rewriter→Qdrant検索→Kimi K2生成） |
| `/oracle deny #一般` | チャンネル単位削除（−513msg/−30chunk、他chは無傷） |
| Botキック | guild単位の全削除（実データ0化、guilds行は left_at 付きで墓標として残存＝設計通り） |

### 途中で直したこと

1. **Query Rewriter が毎回402で失敗**
   - 原因: OpenRouterはmax_tokens未指定時にモデル既定の巨大な出力枠（65535）を
     要求し、残高確保で弾かれる。`rewrite()` が握りつぶして元クエリで検索を続行する
     設計のため回答自体は返るが、書き換えが効かず検索精度が落ちる。
   - 対処: `rag.rewriter_max_tokens`（既定256）を新設し `rewrite()` に渡す。
     残高追加＋本修正で警告ゼロを実測確認。テスト1件追加（全212 PASS・安定順序）。
   - 変更: src/rag/engine.py / config.yml(.example) / tests/test_rag.py（各1コミット）

2. **Qdrantの旧 waiwai_chunks コレクション破損で起動不能**
   - 原因: 前回のDocker停止が不完全で page ファイル欠損。Qdrantが panic 起動失敗、
     連鎖でworkerも落ちた。
   - 対処: `data/qdrant_quarantine/` へ退避（削除せず復元可能）。waiwaiはアクセス禁止
     方針＆元チャンクはPostgresに残存のため実害なし。workerが空コレクションを再生成。

### 補足

- pytest はランダム順序（pytest-randomly）だと test_db 同士の分離揺らぎで稀に1件error。
  安定順序では212件全PASS。今回の変更とは無関係の既存事象（別途要対応）。
- OI-12 を完了に更新。Dockerは起動したまま（次セッションで停止判断）。

---

## 2026-06-11 — SaaS化ステップ2: マルチテナント自動取り込み（feature/multitenant-ingest）

### 目的

「Botをサーバーに導入したら勝手にRAG化して答えてくれる」の取り込み側を実現する。
回答側のテナント分離（Qdrant guild_idフィルタ）はステップ1で実装済みだったため、
今回は **取り込みの自動化・マルチテナント化・opt-in制御** が対象。

### 実装内容

1. **SQLite → Postgres 移行**（ユーザー判断でフルスコープ採用）
   - `src/db.py` を psycopg で全面書き換え。全データ系テーブルに guild_id
   - 新テーブル: `guilds` / `allowed_channels` / `ingest_jobs`（ジョブキュー）
   - Dify遺産（upload_state テーブル・dify_doc_id 列）を廃止
   - `scripts/migrate_sqlite_to_pg.py` で既存waiwaiデータを移行
     （messages 27,769 / chunk_index 8,364 / status='indexed' 保持＝再embedding費用ゼロ）

2. **常駐ワーカー**（`worker.py` → `src/worker.py`・composeの worker サービス）
   - ingest_jobs を `FOR UPDATE SKIP LOCKED` で1件ずつ処理（単一ライター原則を維持）
   - ingest: 許可チャンネルのみREST差分クロール → チャンク → 文脈付与 → Qdrant登録
   - purge_channel / purge_guild: Qdrant + Postgres からデータ削除
   - 定期sync: 最終取り込みから `worker.sync_interval_hours`（24h）経過したguildへ自動投入
   - Discordへはgateway接続せず `client.login()` + REST のみ（Botとのセッション競合なし）

3. **Botのスラッシュコマンド**（`/oracle` グループ・サーバー管理権限のみ）
   - allow: 許可登録+取り込みジョブ投入 / deny: 許可取消+チャンネルデータ削除
   - sync: 差分取り込み即時実行 / status: 件数・最新ジョブ表示
   - on_guild_join: guilds登録+案内 / on_guild_remove: purge_guild（退出=全データ削除）
   - DBアクセスは `store.py`（src/db.py の薄い非同期ラッパー・botビルドはルートコンテキストに変更）

4. **差分sync対応のバグ修正**: `insert_chunk` が chunk_text 変更時に
   context_text だけでなく **status も 'pending' に戻す**ようにした
   （旧実装では伸びた末尾チャンクが再インデックスされない）

5. **guild_name の伝搬**: Bot → /chat → RagEngine。どのサーバーでも
   「そのサーバーの名前」でわいわいちゃんが答える（未指定時は config の値）

### テスト

- DB依存テストを実Postgres（oracle_test DB・conftest.py で TRUNCATE管理）に移行
- 新規: test_worker.py（ジョブ処理・purge・定期sync）ほか
- **211件 全PASS**（旧167件から拡充）

### 残課題

- 実機E2E未実施（OI-12: トークン再発行＋テスト用サーバーが必要）
- 取り込み完了のDiscord通知なし（OI-13: 現状 /oracle status で確認）

### 運用メモ: waiwaiサーバーの扱い

移行スクリプトは既存チャンネルを allowed_channels に登録するが、
**waiwaiサーバーにはもうアクセスしない方針**のため、移行後に waiwai の
allowed_channels 32件を手動削除した（messages / chunk_index / Qdrant のデータは
テスト用に保持。検索・回答は引き続き動く）。
これによりワーカーの定期syncや /oracle sync が waiwai をクロールすることはない。
再度 migrate_sqlite_to_pg.py を実行すると allowed_channels が復活するので注意。

### 状態（2026-06-15更新）

- ブランチ `feature/multitenant-ingest`（50コミット）を push、**PR #6 作成**
  （https://github.com/aigamoid/waiwai-oracle/pull/6 → develop。マージは人間判断）
- 実装・テスト（211件PASS）は完了。次の作業は OI-12 の実機E2E（トークン再発行＋テスト用サーバー待ち）

---

## 2026-06-11 — contextualizer の要否検証（A/Bテスト）

### 背景

contextualizer（Phase 2.5）は処理が重くAPI料金もかかるため削除を検討した。
判断材料として、context_text あり/なしの embedding で検索品質を比較した。

### 方法

- 比較用コレクション `waiwai_chunks_nocontext`（chunk_text のみを embedding）を一時作成
- 同一クエリ5問を両コレクションで検索し top10 を比較（使い捨てスクリプト、本番無変更）
- 終了後に比較用コレクションは削除（費用: 再embedding 約$0.03）

### 結果

| 質問 | top10一致 | 判定 |
|---|---|---|
| 飲み会いつだっけ？ | 4/10 | 引き分け |
| まめぽんの放送機材の話 | 5/10 | contextあり勝ち（なし側は無関係な機材話が混入） |
| マリオカートのレートの話 | 6/10 | contextありやや優勢 |
| Minecraftサーバーが落ちたときの話 | 2/10 | contextあり圧勝 |
| Mac miniをサーバーにする話 | 7/10 | 引き分け（本文にキーワードがある質問は差が出ない） |

決定打: 本文が `<@メンションID>` だけの障害対応チャンクを、context
「Minecraftサーバーのハング対応として再起動と性能増強を行った際の会話」が救った。
1行チャンクが37.4%を占める本データでは context の寄与が大きい。

### 決定事項

- **contextualizer は維持する**（削除しない）
- コストは1サーバーあたり一回 $1〜3 程度で許容範囲
- 実行自体は任意（indexer は context_text=NULL でも動作する設計のため、
  スキップ運用も可能。ただし検索品質は上記の通り低下する）

### 参考: 現在のチャンク粒度（実測）

- 総数 8,364 / 平均 4.9行・203文字 / 1行チャンク 37.4% / 30メッセージ上限到達 2.6%

---

## 2026-06-11 — CLIフロントエンド追加（動作確認用）

### 変更内容

| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/cli.py` | 新規（/chat クライアント・表示整形） |
| 2 | `chat_cli.py` | 新規（REPLエントリポイント） |
| 3 | `tests/test_cli.py` | 新規（ユニットテスト9件） |

### 決定事項

- フロントエンドは **CLIモード / Discord Botモードの2本立てを維持**する
- 両方とも同じ `POST /chat` を呼ぶ薄いクライアント（RAG本体は共有・変更なし）
- CLIは書き換え後クエリ・参照ソース・応答秒数も表示（デバッグ向き）

### 実行結果

- テスト 167/167 PASS
- 実機確認: マリカー大会の思い出を実ログから回答（動作OK）
- Discordトークン再発行前でもバックエンドの動作確認が可能になった

---

## 2026-06-11 — Dify廃止・自前RAGスタック移行（SaaS化ステップ1）

### 変更内容

| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/embedder.py` | 新規（OpenAI embedding・8192トークン超過の切り詰め） |
| 2 | `src/vectorstore.py` | 新規（Qdrant操作・guild_idマルチテナント前提） |
| 3 | `src/indexer.py` / `indexer.py` | 新規（Phase 4: チャンク→Qdrant登録、--all/--clean） |
| 4 | `src/rag/prompts.py` | 新規（Difyフローからプロンプト移植） |
| 5 | `src/rag/llm.py` / `src/rag/engine.py` | 新規（OpenRouter LLM・RAG回答エンジン） |
| 6 | `src/api.py` | 新規（FastAPI: POST /chat, GET /health） |
| 7 | `src/db.py` | indexer用関数追加 |
| 8 | `docker-compose.yml` | qdrant / api / bot サービス追加 |
| 9 | `moimoichan_Discordbot/` | dify_client.py削除 → oracle_client.py、Dockerfile追加 |
| 10 | `tests/` | test_vectorstore / test_indexer / test_embedder / test_rag / test_api 追加 |

### 設計判断

- **Dify廃止**: SaaS化（Botを入れたら自動RAG化）に向け、Difyが担っていた
  ベクトルDB・チャットフロー・APIを Qdrant + 自前Python + FastAPI に置き換え
- **フレームワーク不使用**: LangGraph等は直列3ステップ（書き換え→検索→生成）には過剰と判断。
  検索品質が課題になったら LlamaIndex 導入を検討
- **マルチテナント前提**: Qdrant payload に guild_id を持たせ検索時必須フィルタ
  （テストで他guildデータが見えないことを検証済み）
- **conversation_id 廃止**: APIはステートレス1問1答（応答速度改善の懸案も同時解消）
- **モデル**: rewriter=Gemini 2.5 Flash / 回答=Kimi K2（Difyフローの設定を踏襲）

### ハマりポイント

1. **embedding入力上限**: 実データに8,192トークン超のチャンクが1件あり400エラー
   → tiktoken（cl100k_base）で8,000トークンに切り詰め。`disallowed_special=()` を
   指定しないとチャットログ中の特殊トークン文字列で例外になる
2. **uvicorn直接起動で .env が読まれない**: `src/api.py` に `load_dotenv()` を追加
3. **OrbStackが起動不可**（Migration Assistant起因の権限問題）→ colima で代替。
   恒久対応は `sudo chown -R $USER ~/Library/Group\ Containers/HUAQ24HBR6.dev.orbstack/data`

### 実行結果

- ユニットテスト 158/158 PASS（新規49件）
- 実データ 8,364 チャンクを Qdrant に登録（embedding費 約$0.03）
- E2E確認: ローカルAPI 25.9秒 / コンテナAPI 37.0秒で「わいわいちゃん」回答
  （ソース10件・guild_idフィルタ動作・キャラ口調・実記憶ベースの回答を確認）
- Botコンテナはビルドのみ（起動は本物のDiscordサーバーに繋がるため人間の判断待ち）

### 次のステップ

- Botコンテナ起動 → Discord上での動作確認（人間）
- OI-9（ハイブリッド検索）/ OI-10（会話履歴）/ OI-11（マルチテナント自動取り込み）

---

## 2026-03-25 — GitHub運用整備（PR・ブランチマージ・README）

### 変更内容

| # | ファイル | 内容 |
|---|---|---|
| 1 | `README.md` | 新規作成（プロジェクト概要・セットアップ手順・技術スタック） |

### 実施内容

- GitFlow運用の整備: `develop` ブランチを `main` から新規作成
- `feature/waiwai-oracle` → `develop` をマージ（Fast-forward）
- `feature/moimoichan-discord-bot` → `develop` を初めてのPRで作成・マージ（PR #4）
- `.gitignore` のコンフリクト解消（Accept both changes）
- `README.md` を `develop` に直接コミット

### 決定事項

- `develop` への小さな変更（README等）は直接コミット、機能追加は feature ブランチ + PR
- PR は変更履歴の記録として活用する

---

## 2026-03-25 — Query Rewriter プロンプト最適化・モデル変更

### 変更内容

| # | ファイル | 内容 |
|---|---|---|
| 1 | `dify/waiwai-oracle.yml` | Query Rewriter のモデルを Kimi K2 → Gemini 2.0 Flash に変更、プロンプト全面書き換え |

### 実施内容

- Query Rewriter のボトルネック分析（19.3秒 / 11Kトークン）
- Kimi K2 の問題を特定: 「（会話履歴がありません）」等の不要なメタ発言を出力、thinking モードによるトークン膨張
- モデル候補比較 → Gemini 2.0 Flash を採用（指示遵守・速度・コスト）
- プロンプトを Gemini Flash 向けに最適化（3者レビュー実施）

### ハマりポイント

1. **Kimi K2 の「親切」癖**: 会話履歴が空の場合に「（会話履歴がありません）」と状況報告してしまう。禁止事項を明記しても無視する傾向
2. **few-shot 例の `入力:/出力:` ラベル**: Gemini Flash が `入力: ... 出力: ...` をフォーマットの一部と解釈し、回答にラベルを含めてしまう → `→` 形式に変更で解決
3. **Dify ノードの変数注入**: ユーザークエリが LLM に正しく渡されない問題 → Dify の Memory/Context 設定の確認が必要だった

### 決定事項

- Query Rewriter は **Gemini 2.0 Flash**（`google/gemini-2.0-flash-001`）を使用
- Thinking mode OFF、temperature 0.2
- 曖昧時間語を定義済み（最近=14日、先週=直前の月〜日、先月=前月1日〜末日）
- few-shot 例は `→` 形式で記述（ラベル形式は避ける）

### 実行結果

- 処理時間: 19.3秒 → **0.5秒**（約97%短縮）
- トークン数: 11Kトークン → **465トークン**

### 次のステップ

- メイン LLM ノードの応答速度改善（35秒の短縮）
- conversation_id 無効化プランの実装検討

---

## 2026-03-23 — Discord Bot SSE streaming 対応・Dify Chatflow 連携修正

### 変更内容

| # | ファイル | 内容 |
|---|---|---|
| 1 | `moimoichan_Discordbot/dify_client.py` | blocking → streaming (SSE) モードに全面書き換え |
| 2 | `.gitignore` | `.aider*` を除外対象に追加 |

### ハマりポイント

1. **blocking モードのタイムアウト**: Dify advanced-chat (Chatflow) で `response_mode: "blocking"` を使うと 120秒でタイムアウトする。原因は Squid SSRF プロキシの `request_timeout 2 minutes` がハードコードされているため（Dify Issue #33149）。Web UI は streaming を使うため問題なし
2. **SSE イベント構造の違い**: Chatflow の `message` イベントの `answer` フィールドは累積テキストではなくトークン単位のデルタ。また `message_end` イベントは送信されず、代わりに `workflow_finished` に完全な回答テキストが入る
3. **LLM の `<think>` タグ**: Kimi K2 が chain-of-thought を `<think>...</think>` で返すため、除去が必要
4. **Windows SSH デプロイ**: PowerShell の `Set-Content -Encoding UTF8` は BOM 付きで書き込むため、`.env` / `config.yml` が壊れる → Python スクリプトで書き込みに変更

### 決定事項

- Dify Chat API は streaming (SSE) モードを使用する（blocking は Chatflow と非互換）
- `workflow_finished` イベントの `data.outputs.answer` を正とし、フォールバックでデルタ結合
- Windows 機へのデプロイは scp + Scheduled Task 再起動で運用

### 次のステップ

- 応答速度改善（conversation_id 無効化 or Dify Memory ウィンドウ制限）
- ボットの動作確認（streaming 対応後のエンドツーエンドテスト）
## 2026-03-23 — GitHubプッシュ前 安全性チェック & .gitignore修正

### 変更内容

| # | ファイル | 内容 |
|---|---|---|
| 1 | `.gitignore` | output/, dry_run_result*.txt, .aider.*, dify/, slides/ を追加 |

### 実施内容

- GitHubプッシュ前に機密情報・個人情報のリスクチェックを実施（Codexと協力）
- `.env` / `config.yml` / `data/` はすでに除外済みで安全と確認
- `output/`（Discordメッセージ全文・ユーザー名含む）が未除外だったため追加（高リスク）
- `dry_run_result*.txt`（サーバーID・チャンネルID）、`.aider.*`、`dify/`、`slides/` も追加

### 決定事項

- `dify/` と `slides/` はユーザー判断で非公開（.gitignore追加）
- コミット済みPythonスクリプトはすべて `load_dotenv()` で環境変数読み込み済み → 安全

### ハマりポイント

- 誤って `feature/moimoichan-discord-bot` でコミットしてしまった
  → `git cherry-pick` で `feature/waiwai-oracle` に移植後、`git branch -f` で元ブランチを修正

---

## 2026-03-23 — Dify exportファイル削除・断念確定

### 変更内容

| # | ファイル | 内容 |
|---|---|---|
| 1 | `dify_export.py` | 削除（未コミット・未使用） |
| 2 | `src/dify_exporter.py` | 削除（未コミット・未使用） |
| 3 | `docs/DEVLOG.md` | 「保留」→「断念」に変更、次のステップ削除 |

### 決定事項

- Dify SaaS移行は断念（embedding 設定問題の解決見込みなし）
- `dify_export.py` / `src/dify_exporter.py` はコミット前に削除
- セルフホスト版 Dify 運用継続

---

## 2026-03-23 — `/wrap-up` スラッシュコマンド設計・実装

### 変更内容

| # | ファイル | 内容 |
|---|---|---|
| 1 | `~/.claude/commands/wrap-up.md` | セッション終了処理コマンド新規作成 |
| 2 | `~/.claude/plans/snazzy-nibbling-milner.md` | 実装プランの作成・修正（DEVLOG不在時の確認フロー追加） |

### 実施内容

- セッション終了時に毎回打っていた「ObsidianとDEVLOGに記録・ドキュメント更新」を `/wrap-up` コマンドに自動化
- Claude Code のカスタムスラッシュコマンド仕様を調査（`~/.claude/commands/` 配下に `.md` ファイルを置く形式）
- 現行ワークフローを調査しコマンド内容を設計

### 決定事項

- コマンドは `~/.claude/commands/wrap-up.md`（グローバル配置）とし全プロジェクトで使用可能にする
- `docs/DEVLOG.md` が存在しない場合はユーザーに作成確認を取る（サイレントスキップしない）
- git push はコマンド内に含めない（人間が手動で実施するプロジェクトルールに準拠）

### 次のステップ

- 実際に `/wrap-up` を使い続けてフィードバックがあれば `~/.claude/commands/wrap-up.md` を随時改善する

---

## 2026-03-23 — Dify SaaS移行調査・断念

### 実施内容

- セルフホスト版 Dify → SaaS版への移行手順を検討
- Dify ナレッジベースには UI エクスポート機能がないことを確認
- セルフホスト版 API（`GET /datasets/{id}/documents`・`GET /datasets/{id}/documents/{id}/segments`）でチャンクを全取得 → JSON保存するエクスポートスクリプト案を設計
- SaaS版で「Failed to invoke text embedding」エラー発生 → 原因：SaaS版は embedding モデルの API キー（OpenAI等）をユーザーが持ち込む必要がある（Model Provider 設定が未設定）
- 今セッションは解決に至らず、SaaS移行を一旦保留

### 決定事項

- **Dify SaaS移行は断念**（embedding 設定問題が解消できず）
- セルフホスト版 Dify を引き続き使用する

---

## 2026-03-23 — Dify フロー：現在日時注入

### 変更内容

- `dify/waiwai-oracle.yml` 追加（フローのバージョン管理開始）
- Dify ワークフローに Code ノードを追加（Start → Code → Query Rewriter → Knowledge Retrieval → LLM → Answer）

### Code ノード実装

```python
def main():
    from datetime import datetime, timezone, timedelta
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    return {"current_datetime": now.strftime("%Y-%m-%d %H:%M JST")}
```

**ハマりポイント**: Dify の Code ノードは `def main():` 内に書く必要がある（`return` をトップレベルに書くと `SyntaxError: 'return' outside function`）

### 目的

チャンクテキストに埋め込まれたタイムスタンプを活用し、「最近の話題」「一年前」などの相対時間クエリに対応する。
Query Rewriter と LLM の両プロンプトに `{{#code_node_id.current_datetime#}}` を埋め込んで使用。

---

## 2026-03-22 — Phase 3 再設計完了・RAGチャットボット動作確認

### 主な変更（uploader廃止 → exporter + チャンキング改善）

| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/uploader.py` / `uploader.py` / `tests/test_uploader.py` | 削除（Dify API廃止） |
| 2 | `src/exporter.py` / `exporter.py` / `tests/test_exporter.py` | 新規追加（output/*.txt出力） |
| 3 | `src/chunker.py` | 時間ギャップ方式に全面書き換え（スライディングウィンドウ廃止） |
| 4 | `src/chunker.py` | `_is_noise` 追加・短文吸収ロジック実装 |
| 5 | `chunker.py` | `--clean` オプション追加 |
| 6 | `src/db.py` | `fetch_chunks_by_channel` 追加・INSERT OR REPLACE に変更 |

### チャンキング設計の変更

- **廃止**: スライディングウィンドウ（前後2件）
- **採用**: 時間ギャップ方式（`time_gap_minutes: 60`）
- **追加フィルター**:
  - `_is_noise`: URLのみ・@here/@everyone・空白のみを除去
  - 短文吸収: 10文字以下 + ギャップ60分未満 → 直前チャンクに吸収（疑似reply_to）
  - `@here/@everyone` は短文でも除去
- **結果**: 9,301チャンク → 8,364チャンク（1行チャンク 39% → 37.4%）

### Difyアップロード方式の変更

- **廃止**: Dify Knowledge API 経由の自動アップロード
- **採用**: `exporter.py` で output/*.txt を出力 → ブラウザから手動アップロード
- **理由**: API経由より直感的でエラー内容がわかりやすい
- **Dify設定**: セグメント識別子 `\n\n---\n\n`

### 実行結果

- output/ に 30ファイル / 3.1MB 出力
- Dify にアップロード完了
- **チャットボット動作確認 ✅**

### 3エージェントレビュー記録

- Codex・Aider による複数回レビュー → 短文吸収ロジックの `prev_ts` 更新問題・max_chunk_messages超過問題・空白のみ除去漏れ を指摘・修正済み
- 全テスト 93/93 PASS

---

## 2026-03-21 — チャンキング戦略の調査・方針検討

### 背景

Phase 3（--clean 再アップロード）完了後、チャンク品質の問題が発覚。

### 判明した問題

- セパレータ `\n\n` ＝ メッセージ結合文字 `\n\n` が一致するため **1メッセージ = 1チャンク**
- Dify の分割ロジックは「セパレータで先に分割 → max_tokens で切り詰め」であり、結合ではない
- `max_tokens: 1000` 設定が事実上無効
- 雑談チャンネル単体で 11,305 チャンク（平均 27〜61 文字）→ 検索精度が出ない

### chunker.py の迷走はなかった

- chunker の仕様変更コミットは一度もなし
- 問題は uploader.py がチャンクを使わず messagesテーブルを直接連結している設計上の特性による

### チャンキング戦略の比較調査

| 方式 | APIコスト | 実装難度 | 品質 |
|---|---|---|---|
| 時間ギャップ方式（N時間で区切り） | なし | 低 | △（トピック変化を拾えない） |
| セマンティックチャンキング | embedding ~27,000回 | 中 | ◎ |
| Agentic Chunking | LLM呼び出し多数 | 高 | ◎（コスト最高） |

### 方針（検討中）

- **セマンティックチャンキング** を採用予定
- Dify 側には非対応 → Python 側（uploader.py or 新モジュール）で事前分割
- embedding モデル: OpenAI `text-embedding-3-small`（既存流用）
- 閾値・最小/最大チャンクサイズは実装時に調整
- 実装後は `--clean` で全チャンネル再アップロード

### 残課題

- `👋_ようこそ` の 409 CONFLICT 未解消（Dify UI から手動削除 → `--retry-errors`）

---

## 2026-03-17 — Phase 3 uploader 実装・トラブルシューティング

### 主な変更

| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/formatter.py` | format_message_line + 制御文字除去 |
| 2 | `src/db.py` | upload_state テーブル + 管理関数 |
| 3 | `src/uploader.py` | Dify Knowledge API アップロードロジック |
| 4 | `uploader.py` | エントリポイント（--retry-errors / --clean） |
| 5 | `tests/test_uploader.py` | ユニットテスト 15件 |

### Embedding モデル変更: Ollama bge-m3 → OpenAI text-embedding-3-small

- **原因**: Dify Ollama プラグイン v0.1.2 の ThreadPoolExecutor が並行 embed リクエストを送信するバグ（Issue langgenius/dify-official-plugins#2746）
- **試した対策**: ドキュメント分割・クールダウン・リトライ → すべて無効
- **解決**: OpenAI text-embedding-3-small に切り替えで根本解決

### 意味があった修正のみ残した

| 修正 | 意味 |
|---|---|
| `_wait_for_indexing` で batch ID 使用 | API仕様に合致（document.id は不正） |
| `mark_channel_error` に document_id パラメータ追加 | エラー時も dataset_id 保持 |
| `_create_dataset` 失敗時の UnboundLocalError 修正 | 変数スコープのバグ修正 |
| `_strip_control_chars` 追加（formatter.py） | \x1b/\x1f がJSON破壊するバグ修正 |

### 効果がなかった修正（リバート済み）

- ドキュメント分割（_MAX_MESSAGES_PER_DOC）
- クールダウン（_COOLDOWN）
- リトライロジック（_upload_one_with_retry）

### 実行結果

- 31/32 チャンネル成功（OpenAI text-embedding-3-small）
- 1件エラー: `👋_ようこそ`（409 CONFLICT、前回テスト残存と名前衝突）

---

## 2026-03-15 — Phase 0〜2 実装

- Phase 0: dry_run.py（メッセージ数確認、36,128件 / 39チャンネル）
- Phase 1: crawler.py（Discord → SQLite、7チャンネル除外設定）
- Phase 2: chunker.py（スライディングウィンドウ、前後2件、25,358チャンク生成）
- Dify インストール（Windows 5090機、Tailscale IP: 100.88.176.117）
