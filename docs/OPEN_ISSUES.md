# 未解決事項・TODO

## OI-9: 検索品質（リランキング / ハイブリッド）

旧Difyフローはキーワード0.6/ベクトル0.4のハイブリッド検索 + Jinaリランカーだった。

### ✅ Phase 1: リランカー実装済み（2026-06-17・feature/oi9-reranker）
方式は「dense で多めに取って cross-encoder で精選」（Direction A）。日本語に強く・既存データの
再インデックス不要・OI-16のコスト方針（多く取って絞る）と整合するため、BM25ハイブリッドより先に採用。
- `src/rag/reranker.py`: Jina Reranker クライアント（`jina-reranker-v2-base-multilingual`）。
- `src/rag/engine.py`: `rag.reranker.enabled` の時のみ、dense `top_n`(既定30) → リランクで `top_k` に精選。
  失敗・キー未設定時は dense 順にフォールバック（回答は止めない）。usage_log に `rerank` を記録。
- **既定オフ**（`enabled: false`）。有効化には `.env` の `JINA_API_KEY` ＋ `config.yml rag.reranker.enabled: true`。
- 残: 実データでの品質A/B（top_n・top_k の調整）、pricing単価の実値更新、本番有効化の判断。

### ⬜ Phase 2: スパース(BM25)ハイブリッドは見送り中
Qdrant native の sparse+dense 融合(RRF)は追加API課金ゼロだが、**日本語のBM25分かち書きが弱い**・
全チャンク**再インデックス**が必要。Phase 1 のリランクで品質が足りなければ再検討する。

## OI-10: 会話履歴（マルチターン）対応 ✅ 実装完了（2026-06-17・feature/oi10-multiturn-history）

自前API化に伴い conversation_id を廃止（DEVLOG 2026-03-25 の「無効化プラン」を実施）して
1問1答だった。**Bot/CLI が呼び出し側で直近会話を保持し、毎回 history として API に渡す**
ステートレス設計で対応した（旧 conversation_id 方式は復活させない）。

**実装方式:**
- `src/rag/llm.py`: `complete()` に `history`（古い順 `{"role","content"}` リスト）を追加。
  messages を `system → history → user` の順で組み立てる。
- `src/rag/engine.py`: `answer()`/`rewrite()` に `history` を追加。`_prep_history()` で
  role/content を検証し直近 `rag.history_max_turns` ペアに丸める。**回答LLMだけでなく
  Query Rewriter にも渡す**ので「それ」「さっきの件」等の指示語解決も効く。
- `src/api.py`: `ChatRequest.history` を追加し `answer()` へ素通し。
- `moimoichan_Discordbot/`: `bot.py` が**チャンネル単位** deque で直近やり取りを保持
  （1チャンネル＝1会話）。`oracle_client.py` が history を送る。
- `chat_cli.py`: REPL が履歴を保持（`reset` でクリア）。
- 設定: `rag.history_max_turns`（既定5・0で無効）／ bot config `oracle.history_max_turns`。
- **コスト制御**: 履歴は rewrite/answer 両方に乗るため token が二重計上される（VM本データで実測:
  5ペアで1問あたり約2.5倍 $0.00130→$0.00325）。対策として `_prep_history` に**文字数バジェット**を追加し、
  rewriter には別枠でさらに少なく渡す。新config: `rag.history_max_chars`(4000) /
  `rag.rewriter_history_max_turns`(2) / `rag.rewriter_history_max_chars`(1000)。
- テスト +14件（計266 PASS）。

**残・要確認(人間):**
- 履歴はメモリ上のみ（Bot 再起動で消える・永続化しない）。当面これで十分の想定。
- バジェット既定値（4000字等）は実運用のコスト/品質を見て調整余地あり。
- 関連: OI-16（コスト）/ OI-20（現在日時注入を同ブランチで同時対応）

## ~~OI-11: SaaS化ステップ2（マルチテナント自動取り込み）~~ ✅ 実装完了 (2026-06-11)

feature/multitenant-ingest で実装。
- SQLite → Postgres 移行（psycopg / 全テーブル guild_id 対応 / `scripts/migrate_sqlite_to_pg.py` で既存データ移行済み）
- ingest_jobs ジョブキュー + 常駐ワーカー（worker.py）: allow/sync/定期24h で
  クロール→チャンク→文脈付与→インデックスを自動実行
- 管理者向けスラッシュコマンド `/oracle allow|deny|sync|status`（opt-in方式）
- deny / Bot退出時のデータ削除（Qdrant + Postgres の purge）
- 残り: 実機E2E（→OI-12）、Discord Bot検証・Message Content Intent 審査（100サーバー以上で必要。99までは不要）

## OI-12: マルチテナント取り込みの実機E2E ✅ 完了（2026-06-15）

実装・ユニットテスト（211件）に加え、テスト用Discordサーバー（もいもいAI砂場）で
実機E2Eを完走。全シナリオが想定通り動作した。
- allow→自動取り込み: #一般 511msg→30チャンク→30ベクトル（guild_id分離を確認）
- @メンション回答: 実ログ準拠の回答を確認（Rewriter→Qdrant検索→Kimi K2生成）
- deny: チャンネル単位削除（−513msg/−30chunk、他チャンネルは無傷）
- Bot退出: guild単位の全削除（実データ0化、guilds行は left_at 付きで墓標として残存＝設計通り）

副産物の修正:
- Query Rewriter が OpenRouter で max_tokens 既定値（65535）を要求し残高不足（402）で
  毎回失敗していた → `rag.rewriter_max_tokens`（既定256）を新設して解消。
- 起動時、前回の不完全停止で Qdrant の旧 waiwai_chunks コレクションが破損し起動不能だった →
  `data/qdrant_quarantine/` に退避して復旧（削除せず・waiwaiはアクセス禁止方針のため実害なし）。

## OI-13: 取り込み完了のDiscord通知が無い

ワーカーはジョブ完了を ingest_jobs.result に記録するだけで、Discordへ通知しない
（ワーカーはgateway接続を持たない設計のため）。現状は `/oracle status` で確認する運用。
必要になったら: Bot側でジョブ完了をポーリングして通知する or ワーカーにwebhook URLを渡す。

## OI-14: 収益化・パブリック化ロードマップ（目標）

このBotを一般公開（パブリックBot化）し、サブスクで収益化することを目標とする。
技術基盤（マルチテナント分離・opt-in取り込み・退出時データ削除）は OI-11 で完成済み。
残るのは **法務・Discord審査・コスト管理・課金・インフラ**。以下は領域ごとの課題と改善アイデア
（アイデアベース。着手＝ソース変更・不可逆な操作・方針決定の前には必ず人間に確認する）。

### 進める順番（推奨）
1. OI-12（実機E2E）を完了 ← 公開の大前提
2. 法務(A) + Discord審査(B) ← コード不要、並行で着手可
3. コスト計測(C) ← 課金の前提
4. 課金(D) ← Cの後
5. インフラ(E) ← 顧客が付き始めてから本格化

### A. 法務（最優先・任意ではない）
メッセージ本文を保存し第三者LLM（OpenAI/OpenRouter）へ送信するため、公開・有料化には規約明示が事実上必須。
Discordのbot審査でも提出を求められる。
- **アイデア**: プライバシーポリシー / 利用規約 を作成し、GitHub Pages 等の静的ページで公開。
- **アイデア**: `/oracle allow` 実行時に「このチャンネルの過去ログを外部LLMに送信して学習・回答に利用する」旨の
  同意文を Bot が表示し、管理者の明示同意を取る（同意ログを Postgres に残すと監査に強い）。
- **アイデア**: データ削除請求（GDPR/個人情報保護法の「削除権」）への対応導線。技術的には purge_guild が既にあるので、
  「Botをサーバーから退出させれば全削除される」ことを規約に明記すればまず足りる。
- **要確認(人間)**: 規約の最終文面、適用法域（日本のみ想定か）、運営主体の表記（個人名 or 屋号）。

### B. Discord公式審査
- 100サーバー超で **Message Content Intent の審査**が必要（99までは不要 / OI-11参照）。
- bot verification（認証）と、上記Aの規約URL提出が必要。
- **アイデア**: 公開前に「サポートサーバー」を1つ立て、問い合わせ・障害告知の窓口にする（審査でも好印象）。
- **要確認(人間)**: 公開申請のタイミング（E2E完了後）、運営者情報の開示範囲。

### C. コスト管理（収益化の肝・最も見落とされやすい）
現状 embedding(OpenAI) と 回答LLM(OpenRouter) のコストが **使われるほど青天井**。
guild_id単位の利用量計測・上限が無く、人気が出た瞬間に赤字化するリスク。

**進捗（feature/usage-metering-portal・2026-06-15）:**
- ✅ C-1（計測）実装済み: `usage_log` テーブル新設、`src/rag/llm.py` が usage を返し、
  `src/rag/engine.py` が rewrite/embedding/answer の使用量を `src/usage.py` の
  `UsageRecorder` 経由で記録。コストは config.yml の `pricing` から算出。user_id も記録。
  回答挙動は不変（記録失敗は回答を止めない）。テスト240件PASS。
- ✅ 管理ポータル（`src/admin/`）も同ブランチで実装（下記の追加要望）。
- ⬜ C-2（quota/上限）は未実装。C-1 のデータを見て料金プランを決めてから着手する。
- ⚠️ pricing 単価は概算値。最新の OpenRouter/OpenAI 価格に各自で更新すること。

**当初アイデア（記録用）:**
- **アイデア（計測）**: `usage_log` テーブルを新設し、guild_id・日時・種別(embedding/chat)・トークン数・
  推定コストを記録。既存スキーマが全テーブル guild_id を持つので集計は乗せやすい。
- **アイデア（上限/quota）**: プランごとに「月間質問回数」or「月間トークン上限」を設定し、
  超過時は回答停止 or 課金案内。`src/rag/engine.py` の入口でチェックする想定。
- **アイデア（取り込みコスト）**: 取り込み時の contextualizer(LLM) / embedding もコスト源。
  初回取り込みのチャンク数に応じた従量 or 上限を検討（大規模サーバーが無料枠で大量取り込みすると赤字）。
- **アイデア（モデル選択）**: プランで使用モデルを出し分け（無料=安価モデル / 有料=高品質）してコスト最適化。
- **要確認(人間)**: 料金プラン設計（無料枠の有無・価格・課金単位＝サーバー単位かユーザー単位か）。

### D. 課金システム
- **アイデア**: Stripe でサブスク（Stripe Customer Portal を使えば解約・カード変更を自前実装せず済む）。
- **アイデア**: `guild_plans` テーブルで guild_id ↔ プラン状態(active/past_due/canceled) を管理。
  Stripe Webhook で状態を更新し、未払いは回答停止 or 機能制限。
- **アイデア**: 申込導線は Bot のスラッシュコマンド `/oracle upgrade` → Stripe Checkout のURLを返す。
- **要確認(人間)**: 決済事業者（Stripe想定でよいか）、特定商取引法の表記（日本で課金する場合に必要）。

### E. インフラ・運用
現状はベータ：オンプレ（Mac上の `docker compose` 単一ホスト）。顧客が付くと可用性・バックアップ・監視が課題。

**方針（2026-06-15 決定）: 収益化の必須条件として GCP へ移行する。ベータ期間中に実施。**
→ 実作業手順は **`docs/GCP_MIGRATION.md`**（初心者向けrunbook）。
構成確定: 単一GCE VM(e2-small/東京) + Tailscale経由・公開インバウンド0・月$20以下。

**✅ lift-and-shift 完了（2026-06-15・現状ステージング/検証機）:** Phase 0〜3 完走。
VM `remember-vm`(100.98.83.15) で6サービス本番稼働、取り込み→@メンション回答までGCP上で実機確認。
公開インバウンド0（SSHはIAP範囲のみ）・予算アラート¥3,000設定済み・自動停止 JST 2/9/17時。
詳細は DEVLOG 2026-06-15「GCP移行」。**後に本番機へ移行予定**。
残: バックアップ/監視/Secret Manager化（下記）、Phase6マネージド化。

- **GCP移行アイデア（構成案）**:
  - lift-and-shift（最小手数）: GCE VM 1台で今の `docker compose` をほぼそのまま動かす。
    まずこれでベータ移行 → 後で段階的にマネージド化、が現実的。
  - マネージド化（段階的）: api/admin は **Cloud Run**（ステートレスHTTP）、
    Postgres は **Cloud SQL for PostgreSQL**、Qdrant は永続ディスク付き **GCE/GKE 自前ホスト**
    （or Qdrant Cloud）。Discord Bot と worker は**常駐**なので Cloud Run 不向き → GCE VM か GKE。
  - 機密情報: `.env` → **Secret Manager** へ。
  - データ移行: Postgres は pg_dump/restore → Cloud SQL。Qdrant はスナップショット復元。
  - 公開面: admin/API に独自ドメイン＋HTTPS（マネージドTLS）。Bが進めば公開審査と整合。
- **アイデア（バックアップ）**: Postgres の定期ダンプ + Qdrant スナップショットを自動化。
  移行前のオンプレでもまず実施（Cloud SQL なら自動バックアップが付く）。
- **アイデア（監視）**: `GET /health` を Cloud Monitoring/Uptime checks で外形監視 + ワーカー死活監視。
- **アイデア（スケール）**: 当面は単一構成で十分。テナント増で API/worker を水平分割
  （ジョブキューが FOR UPDATE SKIP LOCKED なのでワーカー複数化は構造的に可能）。
- **アイデア（コスト把握）**: GCP費（Cloud SQL/VM/egress） + API費 を月次集計し、Cの収益と突き合わせ損益分岐を可視化。
- **要確認(人間)**: GCP構成の選択（lift-and-shift で素早く移行 or 最初からマネージド）、
  予算感（Cloud SQL/VMの月額）、移行タイミング、可用性目標、リージョン（東京 asia-northeast1 想定？）。

### F. 管理ポータル（運用ダッシュボード）✅ 初版実装済み
管理者だけがブラウザから全体状況（処理中・料金・在籍サーバー等）を確認できるサイト。
- ✅ `src/admin/`（FastAPI + Jinja2・別 compose サービス `admin`・ポート8001・簡素デザイン）。
  認証は `ADMIN_PASSWORD` の簡易パスワード（HMAC署名Cookie）。
  画面: サーバー一覧（許可ch/msg/chunk/今月コスト）・取り込みジョブ状況・利用量サマリ。
- ⬜ 今後アイデア: 操作系（allow/deny/手動syncをポータルから実行）、期間指定の推移グラフ、
  プラン管理（D課金と連動）、アラート（赤字しきい値超過の通知）。
- **要確認(人間)**: ポータルを公開（外部からアクセス）するか、ローカル/VPN内限定にするか
  （公開する場合は HTTPS 必須・認証強化を検討）。

### 横断的アイデア（収益価値を上げる＝OI-9/OI-10と連動）
- 検索精度向上（OI-9: ハイブリッド検索+リランカー）は有料プランの差別化要素になり得る。
- マルチターン会話（OI-10）も有料機能の候補。

## ~~OI-15: 回答LLMのシステムプロンプト（キャラ/口調）を見直したい~~ ✅ 対応済み（2026-06-17・feature/oi15-prompt-rebrand）

やがて回答プロンプトを変えたい（2026-06-17・対応済み）。コードネーム `remember` への
リブランド（脱waiwai）と連動する。

- 対象: `src/rag/prompts.py` の `ANSWER_SYSTEM_PROMPT`（35行目、キャラ名「れみちゃん」に変更）。
- 変更内容:
  - キャラ名を「わいわいちゃん」から「れみちゃん」に変更
  - 口調・人格を「ゆるゆるふわふわのアシスタント、記憶力があんまりないのんびり屋さん」に刷新
  - AIっぽさ・学術的説明を抑え、友達と雑談するような自然な文章を指定
  - 感情モデル・ENTJ/ENTP等の強いキャラ属性を削除
  - `config.yml.example` の `guild_name` デフォルトを「わいわい」→「みんなのサーバー」に変更
  - 履歴として `prompts/v3_remi_rebrand.md` を追加し、`prompts/README.md` 更新
  - `moimoichan_Discordbot/bot.py` の各種応答メッセージもれみちゃん口調に統一
  - `README.md`/`docker-compose.yml`/`docs/ARCHITECTURE.md`/`docs/DIAGRAMS.md` も併記更新
- 反映: プロンプト・Bot 口調の変更後は **api / bot コンテナを再ビルド**（`docker compose up -d --build api bot`）。
  プロンプトは `prompts/` でのバージョン管理運用（DEVLOG 2026-03-23）に倣うと履歴が追える。
- 関連: OI-14（パブリック化） / 名称検討（codename remember） / OI-16（プロンプト圧縮）
- 検証: テスト 253件 PASS（2026-06-17）

## OI-16: 回答1メッセージのコスト最適化（実測が高い）

GCP移行後の実測（2026-06-15・テストサーバー）で **1問あたり ≈ $0.016（≈¥2.5）** と判明。
事前概算「0.5〜1円」の3〜16倍。OI-14 C-2（quota）・料金設計の前にコスト自体を下げたい。

**内訳（実測・1問）:**
- answer (Kimi K2): **約26,000トークン → $0.016**（ほぼ全部ここ）
- rewrite (Gemini Flash) ≈ $0.00015 / embedding ≈ $0（誤差）

**高い原因:** 回答時の context が巨大。`top_k=10` × 大きめチャンク（`max_chunk_messages=30`）＋
各チャンクに `context_text`（contextualizer出力）も連結しているため、prompt が膨らむ。

**削減アイデア（効果が大きい順・要計測）:**
- **top_k を下げる**（10→5 or 4）: context をほぼ半減できる最大のレバー。`config.yml rag.top_k`。
  トレードオフは再現率（拾い漏れ）。→ OI-9 リランカーと併用すれば少数精鋭で品質維持しやすい。
- **回答に渡す context を絞る**: `src/rag/prompts.py build_context` で context_text を外す or 短縮、
  チャンク本文を上限文字数でトリム。context_text は主に検索用なので回答prompt から省く余地あり。
- **回答の出力上限**: answer 呼び出しに `max_tokens` を設定し completion を上限化（engine.answer）。
- **モデル出し分け**（OI-14 C-2）: 無料プランは安価モデル、有料は Kimi K2。`rag.answer_model` をプラン別に。
- **システムプロンプト圧縮**（OI-15）: わいわいちゃんプロンプトの冗長部を削るとprompt tokenも減る。
- **チャンク設計の見直し**: `max_chunk_messages` を小さくして1チャンクを軽量化（再取り込みが必要）。

**進め方:** `usage_log` で before/after を計測しながら top_k から試すのが安全（回答品質と
コストのトレードオフを実データで見る）。反映後は api 再ビルド（`docker compose up -d --build api`）。
**要確認(人間):** 品質とコストのどちらをどこまで優先するか（無料/有料で別設定にするか）。
関連: OI-14 C（コスト/quota）/ OI-9（リランカー）/ OI-15（プロンプト）

**対応済み（2026-06-16・バランス案）:**
- `top_k` 10→5（context ほぼ半減）。`answer_max_tokens: 1500` を新設（completionの暴走防止・安全弁）。
- `answer_model` を Kimi K2 → **DeepSeek V3.2** に変更。`pricing` も OpenRouter実価格に更新。
- A/B計測（`scripts/ab_cost_test.py`・同一context・top_k=5・2問）:
  - Kimi K2: $0.0058 / $0.0094（平均 ≈ $0.0076/問）
  - DeepSeek V3.2: $0.0017 / $0.0029（平均 ≈ $0.0023/問・約1/3）→ 品質（キャラ語尾/絵文字/Markdown）も同等
- 総合: 元 **$0.016**（top_k=10・Kimi）→ **≈ $0.002〜0.003/問**（約1/6〜1/7）。
- 残レバー（未着手）: context_text を回答promptから省く（OI-9リランカー併用時）・モデル出し分け（OI-14 C-2）・
  プロンプト圧縮（OI-15）。品質劣化が見えたら top_k を 6〜7 に戻す。

## OI-17: 回答LLMにDiscordツール（function calling）を持たせるか → 当面見送り

検討メモ（2026-06-16）。結論は **当面見送り**。

**前提:** Kimi K2 は OpenRouter 経由で function calling 対応＝技術的には可能。
ただし API（`src/rag/engine.py`）は現状 Discord 非接続のため、エージェントのループ
（LLMがツール要求→裏でDiscord実行→結果を戻す→続き）と Discord 権限の追加が必要で作りが変わる。

**ツールで嬉しい候補:** ①読み取り/鮮度（未取り込みの直近メッセージ取得）②読み取り/解決
（`<@ID>`→表示名、チャンネル解決）③アクション（投稿・スレッド・イベント・リマインド）。

**見送りの理由:**
- コスト増: LLM往復が複数回×巨大context で1問のコストが数倍。OI-16（コスト削減）と逆行。
- レイテンシ増（現状20〜40秒がさらに伸びる）。
- プロンプトインジェクション: LLMはユーザーのチャット本文を読むため、悪意ある投稿が命令に化ける。
  アクション系（投稿/キック/ロール）は公開マルチテナントbotで特に危険 → 当面持たせない。
- スコープ拡大: 「過去ログを思い出すbot」から汎用Discordアシスタントへ別物化。

**方針:** いま欲しい効果の大半はツールなしで実現できる。
- 「`<@ID>`が誰か」は LLMツール不要・決定論的に解決できる → **OI-18 で先に対応**。
- 「鮮度」はツールより sync 間隔短縮（OI-13/24h設定）で足りる場合が多い。
- エージェント的ツールは OI-14（公開/収益化）・OI-16（コスト）が片付いた後、まず**読み取り限定**で再検討。
- 関連: OI-18 / OI-16 / OI-14 / OI-13

## OI-18: 回答中の `<@ID>` メンションを表示名に解決 ✅ 実装完了（2026-06-16・feature/oi18-mention-resolution）

チャットログは `<@123...>` 形式のメンションだらけで、回答に出ると「誰の発言か」が伝わらない。
LLMツール使用（OI-17）に頼らず**決定論的に表示名へ置換**することで低コスト・低リスクで品質を上げた。

**採用方式: 取り込み時に解決して chunk_text に保存**（回答時の追加コストゼロ＝OI-16と整合）。
- `src/formatter.py`: `resolve_mentions()` 追加。`format_message_line` に任意の `mention_map` 引数。
  `<@ID>` / `<@!ID>` → `@表示名`。map に無いIDは原文のまま（ロール `<@&ID>`・チャンネル `<#ID>` は対象外）。
- `src/db.py`: `fetch_mention_map(conn, guild_id)` = messages から `author_id→表示名`（最新を採用）。
- `src/chunker.py` / `src/contextualizer.py`: 取り込み時に map を構築し chunk_text と
  preceding_messages を解決。テスト +13件（計253 PASS）。

**効果（実測）:** 既存データの **7.3%（614/8395）** のチャンクが生 `<@ID>` を含んでいた。

**残・要確認(人間):**
- 既存チャンクは**再取り込みで反映**（`insert_chunk` が本文変更で再indexする）。次回syncで自然に更新。
  即時反映したい場合のみ手動 re-chunk（再embeddingコスト・OI-16注意）。
- 未発言ユーザー（lurker）の `<@ID>` はDBに名前が無く未解決のまま。必要なら将来 Discord REST で補完。
- 関連: OI-17（ツール使用の代替）/ OI-16（低コスト維持）

## ~~OI-1: dry_run.py 未実行~~ ✅ 完了 (2026-03-15)
総メッセージ数: 36,128件 / 推定チャンク数: 35,994件（除外前）。
ノイズチャンネル7本を config.yml の exclude_channel_ids に追加済み。
除外後の推定: 約27,769件 / 32チャンネル。

```bash
docker compose run oracle python dry_run.py
```

## ~~OI-2: Dify未インストール~~ ✅ 完了 (2026-03-15)
Windows 5090機（100.88.176.117）にDifyをインストール・起動済み。
- ナレッジベース `waiwai-discord` 作成済み
- dataset_id: `58358a2f-d3b9-4d0e-ae70-bf4812a1ba95` → config.yml反映済み
- DIFY_API_KEY → .env反映済み
- curl接続テスト成功

## ~~OI-7: チャンク品質問題~~ ✅ 完了 (2026-03-21)

時間ギャップ方式（`time_gap_minutes: 60`）に移行し解消。
- `src/chunker.py` を全面書き換え（スライディングウィンドウ廃止）
- 1チャンネル 11,305 チャンク → 会話単位の大幅削減見込み
- `python chunker.py --clean` で旧データ削除後に再生成する

## ~~OI-8: 👋_ようこそ の 409 CONFLICT~~ ✅ 解消 (2026-03-21)

Dify アップロード廃止（`exporter.py` によるファイル出力方式に移行）により、
API 経由のアップロード自体がなくなったため問題消滅。

---

## OI-19: worker の `Event loop is closed` 警告（無害・既知事項）

GCP検証機の取り込み中、worker ログに `RuntimeError: Event loop is closed`
（`Task exception was never retrieved` / httpx `AsyncClient.aclose()` 由来）が散発する
（2026-06-17・重いサーバー取り込み時に確認・60分で3回）。

- **影響なし**: 取り込みは全ジョブ done・`error_message` 空、chunk_index 件数と Qdrant
  ベクトル数も一致（543=543）。終了時の後始末ログのノイズで、データ・機能に害はない。
- **原因（推定）**: worker がジョブごとに asyncio ループを回す際、非同期HTTPクライアント
  （embedder/contextualizer 等）を明示クローズせず、GC時にループ閉鎖後の `aclose()` が走るため。
- **対応方針**: 急がない。検証が一段落したら根本対応を1コミットで
  （非同期クライアントを明示 `aclose()` する / ループを跨がない作りにする）。
  放置するとログに常駐し本物のエラーを埋もれさせるので、いずれ潰す。

## OI-20: 回答LLMが現在日時を知らず過去ログの日付を「今日」と誤認 ✅ 修正済み（2026-06-17・feature/oi10-multiturn-history）

**症状:** 「今日」を実日付（6/17）でなく過去ログ内の日付（例: 5/6）と誤認して回答していた。
過去メッセージ「5/6に集合ね！」がヒットし、それを今日の予定として答えるなど。

**原因:** `REWRITER_SYSTEM_PROMPT` には `現在の日時（JST）` が注入されていたが、
**回答プロンプト `ANSWER_SYSTEM_PROMPT` には現在日時が一切入っていなかった**
（`src/rag/engine.py` の `answer()` は guild_name と context しか差し込んでいなかった）。
回答LLMは「今」を知らないまま、日付付きチャンクを読んで過去か現在かを判断できなかった。

**修正:** `ANSWER_SYSTEM_PROMPT` に `## 現在時刻` セクション（`{current_datetime}`）を追加し、
`engine.answer()` で `_now_str()` を差し込む。あわせて「記憶の断片はすべて過去の記録であり、
相対表現や予定は記憶内の日付でなく現在時刻を基準に判断する」旨の一文を明記
（日付を渡すだけでなく過去/現在の前後関係を考えさせる）。テストで現在日時が回答プロンプトに
入ることを検証。OI-10（会話履歴）と同ブランチで対応。
- 反映には api 再ビルドが必要（`docker compose up -d --build api`）。

## OI-3: ThreadCollector 未実装
現在はTextChannelのみ取得。スレッド対応は将来実装。
`collectors/base.py` のABCは拡張を前提に設計済み。

## ~~OI-4: Discord Message Content Intent 確認~~ ✅ 完了 (2026-03-15)
MESSAGE CONTENT INTENT がONになっていることを確認済み。

## ~~OI-5: Dify Knowledge APIのチャンク数上限確認~~ ✅ 解消 (2026-03-16)
チャンネルごとに1ナレッジベース・1ドキュメントに変更したため、上限問題は解消。
（調査結果: セルフホスト版に上限なし。ただし100件超でリトリーバル不具合の報告あり — GitHub #29750）

## ~~OI-6: Dify メタデータフィルタの扱い~~ ✅ 決定済み (2026-03-15)

### 結論: Dify の自動メタデータフィルタは使用しない

**調査結果:**
- Dify セルフホスト版の自動メタデータフィルタにバグ多数（GitHub Issue #16564, #29556 など）
- 実用に耐えないと判断

**採用した代替策:**
- タイムスタンプ・投稿者名などのメタデータを `chunk_text` 本文に直接埋め込む
- フォーマット: `[YYYY-MM-DD HH:MM] 投稿者名: メッセージ内容`
- タイムスタンプは JST 変換済み（`config.yml` の `timezone_offset: 9` で制御）

**理由:**
- 「去年の5月何話してたっけ？」のような時系列クエリに対し、chunk_text にタイムスタンプが含まれるため LLM が回答できる
- exporter.py 側でメタデータフィルタ設定が不要になり実装が簡素化される
