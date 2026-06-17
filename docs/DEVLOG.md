# DEVLOG

Phase ごとの作業記録・設計判断ログ。

---

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
