# 未解決事項・TODO

## OI-28〜43: 魅力強化（リテンション・課金理由）アイデア群（未着手・アイデア段階）

収益化に向け「お金を注ぎ込みたくなる魅力の核」を増すための案。OI-14（収益化ロードマップ）の
**横断的アイデア（収益価値を上げる）**を具体化したもの。**いずれもアイデア段階**で、着手＝ソース
変更・方針決定の前には必ず人間に確認する（OI-14 と同じ流儀）。

**前提となるコンセプト転換:** 今の remember は「聞かれたら答える**検索ツール**」設計。勝ち筋は
「コミュニティの共有記憶を持った**"れみちゃんという一員"**」＝*そこに居て・覚えていて・自分から
思い出させてくれる存在*への格上げ。ChatGPTメモリ=個人の記憶／MEE6等=管理機能 に対し、
**"コミュニティの共有脳"** は空いた陣地で、ここが堀になる。

**市場調査（2026-06-22・Web）でわかった「魅力の核」3類型:**
①ゲーミフィケーション/エンゲージ（MEE6レベリング・Tatsuペット・CommunityOneクエスト）
②AIの人格・記憶・愛着（Clyde・Shapes friendship meter）③キャッチアップ/要約（SummaryBot・Discord公式）。
教訓2つ: **MEE6は過度な収益化で評判を落とした**（出し惜しみは毒）/ **Discordが要約を公式実装**
（単純機能はコモディティ化＝差別化必須）。

**優先度サマリ（推奨）:**
- **高**: OI-29（記憶ベースクエスト）/ OI-28（関係性メーター）/ OI-33（プッシュ型思い出し）
  ＝実証済みリテンション装置を自社の堀（記憶）で動かす中核。
- **中**: OI-30（スケジュールダイジェスト＋記憶）/ OI-32（知識貢献エコノミー）/ OI-31（カスタム人格）/
  OI-35（公式FAQ）/ OI-36（メンバープロファイル）/ OI-37（記憶の可視化）。
- **要検討（低）**: OI-34（オンデマンド要約）＝Discord公式と競合する赤い海。記憶連携で差別化できる時のみ。

**Codexコメント（ClaudeCode向け・2026-06-22）:**
- 収益化の勝ち筋は「機能の有無」より「毎日戻る体験」。検索ツールから、共有記憶を育てる存在への転換を優先。
- 実装順は **OI-29 -> OI-33 -> OI-28/OI-37** を推奨。まず OI-29 を MVP（週3クエスト+達成ログ+軽い可視化）で小さく検証。
- 無料プランは体験を壊さず、有料で継続体験の深さを増やす（出し惜しみで体験を壊さない）。
- スパム化防止を最優先: 頻度上限、quiet hours、opt-out を初期から入れる。
- 管理者価値（財布に近い層）を並走強化: OI-35（公式ナレッジ/FAQ自動応答）を中期で当てる。
- 追うKPI: 7日/28日継続率、DAU/WAU、Free->Pro/MAX転換率、通知ミュート率（スパム兆候）。

---

### OI-28: れみちゃんとの「関係性が育つ」メーター（高・リテンション中核）
- **着想元**: Shapes.inc の *"friendship meter that tracks interactions, unlocking escalating joke
  complexity with loyal users"* / *"remembers your chats and evolves with them"*
  （[bestaitools: Shapes](https://www.bestaitools.com/tool/shapes/) / [Shapes公式](https://shapes.inc/discordbot)）。
- **私の考え**: remember は既に memories＋発言者名（OI-22/24）を持つ。**ユーザー単位の"覚えてる量"を
  関係性レベルに変換**し、レベルで口調が砕ける/特別な思い出話を解禁。Shapesは個人記憶で愛着を作るが、
  remember は*コミュニティ共有*記憶という彼らに無い深さで同じ機構を回せる。**解約率を下げる核**。
- **既存資産**: memories / speaker（OI-22/24）。**リスク**: 数値の見せ方を誤ると作業感。関連: OI-37/OI-24。

### OI-29: 記憶ベースのパーソナライズド・クエスト（高・最有力）
- **着想元**: CommunityOne Hype Engine = 活動/興味に合わせたAI生成デイリークエストで
  *"10× higher 28-day retention"*・*"4× daily chat"*、かつ *"encourages quality interactions"*
  （スパム加点のレベリングと対比）（[Hype Engine](https://communityone.io/hype-engine/) /
  [Discord Quests](https://communityone.io/discord-quests/)）。
- **私の考え**: クエストは効果実証済みの最強リテンション装置。他社は「行動データ」だけでパーソナライズ
  するが、remember は**サーバーの会話内容そのもの**を知っているので「先週ゲームの話してた○○さんに
  話しかけてみよう」等の*記憶由来クエスト*が作れる＝**誰も真似できないパーソナライズ**。エンゲージ機能を
  自社の堀（RAG記憶）で動かす形。**リスク**: クエスト品質のばらつき・スパム誘発回避。関連: OI-32/OI-33。

### OI-30: スケジュール配信ダイジェスト（＋記憶で差別化）（中）
- **着想元**: SummaryBot *"/schedule … recurring daily or weekly digests without anyone running a
  command"*（[SummaryBot](https://discordsummarybot.com/)）。ただし **Discord公式が In-Channel
  Summaries を実装済み**（[Discord Support](https://support.discord.com/hc/en-us/articles/12926016807575-In-Channel-Conversation-Summaries) /
  [Engadget](https://www.engadget.com/with-the-help-of-openai-discord-is-finally-adding-conversation-summaries-160030905.html)）。
- **私の考え**: オンデマンド要約は公式に飲まれた赤い海。勝ち筋は**長期記憶を絡めた定期ダイジェスト**
  ＝「今週の#雑談まとめ＋*先月の同じ話題との比較*＋覚えてる予定のリマインド」。"いま"しか見ない公式に対し
  "過去と繋いで思い出させる"のがうちだけ。Pro/MAXの定期配信機能に。**既存資産**: 時系列チャンク。関連: OI-34。

### OI-31: サーバーごとに人格・名前をカスタムできる"そのコミュニティのれみ"（中）
- **着想元**: Clyde は *personality field・presets・名前/アイコン変更* を提供し会話に編み込まれたが、
  *永続人格/記憶が無い*まま**廃止**された（[Discord Wiki: Clyde](https://discord.fandom.com/wiki/Clyde_(chatbot)) /
  [vibebot](https://www.vibebot.gg/blog/discord-ai-bots)）。
- **私の考え**: Clydeが愛された理由（カスタム人格）と死んだ理由（記憶が続かない）は表裏。remember は
  **Clydeに無かった永続記憶を既に持つ**。ここに*サーバーごとのリネーム＋人格チューニング*を足せば
  「うちのサーバーだけの、記憶を持つマスコット」になる＝Clydeが成れなかった製品。人格カスタムは
  有料の差別化ゲートにしやすい。**リスク**: プロンプト管理・ガードレール（OI-14 A）。関連: OI-15。

### OI-32: 「知識を教えると育つ」貢献エコノミー（中）
- **着想元**: Tatsu は経済/ペットで *"increase how long people stick around"*、Hype Engine は
  *スパムでなく質の高い貢献*に報酬（[peakbot](https://peakbot.pro/blog/mee6-vs-dyno-vs-carl-bot-2026) /
  [Hype Engine](https://communityone.io/hype-engine/)）。Tatsuはレベル報酬を*無料*にしてMEE6と差別化。
- **私の考え**: 一般の経済系は「喋る＝加点」でスパムを生む。remember なら**「良い事実を"覚えておいて"で
  教える」「良い質問をする」＝Botの記憶を育てる行為に報酬**を出せる。*エンゲージ報酬*でありながら
  **自社の資産（記憶＝堀）をユーザーに育てさせる**二重の効き。プロダクト名 `remember` と一致。
  「みんなで育てたから解約できない」を作る。関連: OI-24/OI-29/OI-37。

### OI-33: プッシュ型「思い出し」（On This Day / さりげないリマインド）（高）
- **着想元**: ゲーミフィケーション/能動接触が *"lasting user interest"* を生む
  （[IONOS](https://www.ionos.com/digitalguide/online-marketing/social-media/discord-bots/)）。
- **私の考え**: 受動RAGは「用がある時しか開かない」。れみちゃんが**自分から**「1年前の今日こんな話で
  盛り上がってたよ📷」「もうすぐ○○さんの誕生日だよ（前に覚えたやつ！）」と投下＝毎日の接触＝定着＋
  "想い出が蘇る"感情価値。ログ（時系列チャンク）＋memories両方が活きる。worker の定期実行に乗る。
  **リスク**: 頻度を誤るとスパム化→頻度をプラン/設定で制御。関連: OI-28/OI-24/OI-13。

### OI-34: オンデマンド要約「見てない間に何があった？」（要検討・低）
- **着想元**: SummaryBot/Catch Me Up 等の *catch up* 系（[SummaryBot](https://discordsummarybot.com/)）。
  ただし**Discord公式が同等機能を内製化済み**（OI-30 出典参照）。
- **私の考え**: 「昨日の#雑談まとめて」は課金理由が明確（時間節約）だが、**公式と正面衝突する赤い海**。
  単独では弱い。OI-30（記憶連携の定期ダイジェスト）に**吸収して差別化**するのが筋。単体着手は非推奨。
  関連: OI-30。

### OI-35: 管理者がBotを"育てる"公式ナレッジ / FAQ自動応答（中）
- **着想元**: 課金を決めるのは運営者。Dyno等の有料差別化は運営支援（モデ/連携）に集中
  （[peakbot](https://peakbot.pro/blog/mee6-vs-dyno-vs-carl-bot-2026)）。
- **私の考え**: 「サーバーのルールは？」「次のイベントいつ？」に過去ログ＋**管理者が公式に覚えさせた事実**で
  自動回答。memories に「公式」レイヤーを足す（`/oracle teach` を一般の「覚えておいて」と分離）。
  運営工数を直接削る＝最も財布に近い相手に刺さる。「Botを育てる」体験が愛着と乗り換えコストを生む。
  **既存資産**: memories 書き込み経路（OI-24）。関連: OI-24/OI-32。

### OI-36: メンバープロファイル / 「あの人どんな人？」カード（中）
- **着想元**: コミュニティ固有価値はゲーミフィケーション系の差別化軸（[IONOS](https://www.ionos.com/digitalguide/online-marketing/social-media/discord-bots/)）。
- **私の考え**: 過去ログ＋memoriesから各メンバーの興味・好み・口癖を要約したカードを生成
  （「@○○ ってどんな人？」「ケーキ好きの人いた？」）。**汎用botにもChatGPTにも作れない**コミュニティ固有資産で、
  新規参加者のオンボーディング価値が高い。**既存資産**: OI-22（speaker）/OI-18（mention解決）の延長。
  **リスク**: プライバシー必須→本人opt-out・センシティブ属性ガードレール（OI-14 A / プロンプトv4の宿題）。

### OI-37: 記憶の"育つ"可視化（プロダクト名 remember の回収）（中）
- **着想元**: Tatsu/CommunityOne の成長・貢献の可視化が定着を生む（[peakbot](https://peakbot.pro/blog/mee6-vs-dyno-vs-carl-bot-2026) /
  [Hype Engine](https://communityone.io/hype-engine/)）。
- **私の考え**: 「れみちゃんは今このサーバーのことを **312件** 覚えています」「今月 **47回** 助けました」。
  **プロダクト名と完全に整合**。成長/貢献の可視化は愛着＝解約率低下に効き、集計データ（usage_log /
  chat_trace）も既にある。Botの一言＋管理ポータル表示を足すだけで形になる。関連: OI-28/OI-32.

### OI-38〜42候補: Codex追加アイデア（2026-06-22・未着手）
- **OI-38: Memory Moments（週1の思い出ハイライト）**
  - 概要: 「今週の盛り上がり」と「過去の似た話題」をセットで自動投稿する。
  - 既存OIに対する利点: OI-30/OI-34 の要約価値を、**過去との接続**に拡張できる。Discord公式要約との正面競合を避けやすい。
  - 関連: OI-30/OI-33。
- **OI-39: Quest Streak（連続達成ボーナス）**
  - 概要: OI-29 のクエストに「連続達成」概念を追加し、称号や軽い演出で習慣化を促す。
  - 既存OIに対する利点: OI-29/OI-32 を土台に、単発参加で終わらせず**継続行動**に変換しやすい。
  - 関連: OI-29/OI-32。
- **OI-40: Server Memory Capsule（月次レポート）**
  - 概要: 「今月覚えたこと」「助けた回数」「FAQ寄与」などを1枚で可視化する管理者向けレポート。
  - 既存OIに対する利点: OI-37 の可視化を**運営者ROI提示**へ昇格できる。課金継続判断に直結しやすい。
  - 関連: OI-37/OI-35。
- **OI-41: Proactive Warm Ping（静かな会話再点火）**
  - 概要: OI-33 のプッシュを、個人通知より低圧な「チャンネル向け話題振り」に寄せる。
  - 既存OIに対する利点: OI-33 のスパムリスクを抑えつつ、サーバー全体の再訪・再会話を起こしやすい。
  - 関連: OI-33。
- **OI-42: Admin Copilot Pack（運営向け導入バンドル）**
  - 概要: `/oracle teach`（公式知識投入）+ FAQ応答 + ルール案内テンプレを運営向けにパッケージ化。
  - 既存OIに対する利点: OI-35 を単機能でなく**導入価値セット**として提示でき、Pro/MAXの価格説明がしやすい。
  - 関連: OI-35/OI-24。

### OI-43: 「真似っこ」モード（メンバーをプロファイリングして憑依させる）（高・愛着/話題性）
- **着想元**: ユーザー発案（2026-06-22）。「`/oracle mimic @○○` で人を指定 → その人をプロファイリング →
  『○○さんの模倣をはじめるね。まず○○さんはこういう人で、こう呼ばれていて、性格は〜、好きなものは〜、
  話し方は〜』と宣言 → 以降そのサーバーで○○さんの口調・性格・特性で話すようになる」。
- **私の考え**: 新機能というより **OI-36（メンバープロファイル）× OI-31（人格カスタム）の合体・昇華版**。
  「あの人どんな人？」カード（OI-36）で生成した人格を、人格差し替え枠（OI-31）に流し込んで*憑依*させる
  体験にする。検索ツールから「そこに居る存在」への転換（OI-14 横断アイデア）に直結し、話題性・愛着
  （OI-28）が強い＝SNSで言及されやすい魅力の核。
- **既存資産（ほぼ揃っている）**:
  - 発言データ: `messages`（author_id/author_name 付き）から対象者の発言だけ集約可能。
  - メンション解決: OI-18 で `<@ID>`→表示名が確定済み。
  - 人格差し込み口: `ANSWER_SYSTEM_PROMPT`（src/rag/engine.py）は `{guild_name}`/`{speaker_section}`
    等を差し替える作り。**「真似する人格ブロック」を1枠足すだけ**で口調・性格を上書きできる。
  - 発言者名を渡す経路: OI-22 で「いま話す人」をプロンプトに渡す仕組みあり。
- **最小形（着手時に要検討・まだ実装しない）**:
  - `/oracle mimic @ユーザー`: 対象者の発言を集約 → LLM で人格カード生成（名前・呼ばれ方・性格・好き・
    口調）→「○○さんの模倣をはじめるね…」と宣言（発案そのまま）。
  - 生成カードを保存（memories 流の別テーブル）し、以降そのチャンネル/サーバーの回答プロンプトに
    人格ブロックとして注入。`/oracle mimic off` で解除。状態（誰を真似中か）を guild/channel 単位で保持。
  - コスト: プロファイル生成は1回 LLM を回すだけ。保存すれば回答時の追加コストは小さい（OI-16と整合）。
- **リスク（重め・公開前に必須）**:
  - **プライバシー/なりすまし**: 実在の人を AI が演じるため、からかい・なりすまし・本人が嫌がる用途の温床。
    **本人 opt-out（むしろ opt-in 必須化も検討）**・センシティブ属性ガードレール（OI-36/OI-14 A の宿題と共通）。
  - 模倣品質のばらつき（発言が少ない人は薄いカードになる）。誇張・揶揄に倒れない生成プロンプト設計。
- **関連**: OI-36（プロファイル生成＝素材）/ OI-31（人格差し替え＝器）/ OI-22（発言者名）/ OI-18（mention解決）/
  OI-28（愛着）/ OI-14 A（法務・センシティブ属性）。

### OI-44〜51: codex-fugu 安全性レビュー指摘（収益化・公開前提）（2026-06-22・未着手）

read-only レビュー（コード変更なし）の所見。**魅力強化（OI-28〜43）とは別系統＝「身内ベータ→
公開/課金の手前」へ上げるための安全性・運用課題**。指摘はレビュー時点のもので、**着手前に各自で
live code を再確認**すること（特にP0は実装と突き合わせてから直す）。

参考（レビュー時）: pytest 368収集 / 217 passed / 151 skipped（DB系はローカルPostgres未接続でskip・
CIでは走る）。警告: FastAPI `@app.on_event` deprecated / ローカル .venv が Python 3.9.6（README/CI/
Docker は 3.11+）/ urllib3+LibreSSL。良い点: マルチテナント分離・opt-in設計・C-2 quota/plan・
usage/cost logging＋admin portal・RAG段階整理・テスト数の多さは収益化の土台として評価。

- **OI-44（P0）: Bot退出/purge の削除範囲が不完全（プライバシー）**
  - 指摘: `purge_guild_data()` は attachments/messages/chunk_index/crawl_state/allowed_channels は
    消すが、**memories・usage_log・chat_trace・guild_plans・ingest_jobs・run_log が残る**。
    特に **memories / chat_trace はユーザー発話・明示記憶・ヒットチャンク本文を含む**ため、README/
    規約の「Bot退出で全削除」と実装が食い違う。
  - 対応案: purge対象に memories/chat_trace を追加（最低限）。会計監査で残す usage_log/guild_plans は
    本文/個人列の削除 or 匿名化＋保持ポリシー明文化。`tests/test_db.py` に削除/保持ポリシーのテスト追加。
    README/規約の表現を実装に一致させる。関連: OI-14 A / OI-21 / OI-24。

- **OI-45（P0）: /chat API が認証なし・guild_id がクライアント指定**
  - 指摘: `src/api.py` の `/chat` は guild_id をリクエストから受けそのまま検索に使い、Bot発であることを
    検証する認証/署名が無い。`docker-compose.yml` で API が `8000:8000` でホスト公開されているため、
    外部到達する配置だと**他guildの文脈検索・quota消費・LLMコスト発生**のリスク。
  - 対応案: Bot→API 間に共有シークレット（例 `X-Oracle-Token`）。API側で guild_id と bot-origin を検証。
    本番は API/admin の公開範囲を Tailscale/VPN/内部網に限定。将来公開時は gateway/auth/rate limit。
    関連: OI-14 E（インフラ）/ OI-46。

- **OI-46（P0/P1）: /remember が quota 管理外でコスト発生・記憶汚染**
  - 指摘: 質問quotaは `/chat` 入口で見るが、`/remember` は quota check なしで LLM抽出を実行。
    「覚えておいて」連打で **memory_extract のLLMコスト発生**、`count_questions_since()` は
    `kind='answer'` だけ見るため**日次上限にカウントされず**、memories がスパム/汚染される抜け道。
  - 対応案: `/remember` も quota/rate limit 対象に（最低 guild/user/channel 単位の短時間 rate limit）。
    明示メモリ書き込みを管理者限定 or モデレーション可能に。`/oracle memory list/delete` 管理導線。
    関連: OI-14 C-2 / OI-24 / OI-47。

- **OI-47（P1）: 明示メモリ機能の安全弁が薄い（config で有効化済み）**
  - 指摘: `config.yml rag.memory_enabled: true`。誰でもサーバー全体の長期記憶を書け、センシティブ属性・
    個人情報・悪意ある虚偽の保存ガードが弱い。全件注入のためmemories増でプロンプト肥大。削除/一覧/
    監査UIが未見。
  - 対応案: memories に moderation status を持たせ管理者承認制 or 信頼ユーザー限定。件数上限・古い記憶の
    要約・関連memoryだけ検索注入（Qdrant化＝OI-24後段）。管理ポータルに memory 管理。purge対象化（OI-44）。
    関連: OI-24 / OI-44 / OI-14 A。

- **OI-48（P1）: 公開/課金前の同意ログが未実装**
  - 指摘: `/oracle allow` は opt-in 設計として良いが、**過去ログ本文の保存・外部LLM送信・料金/quota/削除
    ポリシーへの明示同意ログ**を取っていない。OI-14 A のとおり公開・有料化では必須級。
  - 対応案: `/oracle allow` 初回に同意文表示＋`consent_log` テーブル（同意した管理者ID・日時・対象ch・
    規約バージョン）。`/oracle allowall` は全ch対象ゆえ強めの確認。関連: OI-14 A / OI-25。

- **OI-49（P1）: CD のヘルスチェックが API の /health だけ**
  - 指摘: develop push → runner → `docker compose up -d --build` → `/health` 確認、の成功判定が API のみ。
    **bot/worker/admin/Postgres・Qdrant実接続/実 /chat 動作/job処理が落ちていても成功扱い**になりうる。
  - 対応案: compose に `restart: unless-stopped` / `healthcheck` 追加。CD後に `docker compose ps` 確認。
    `/health` を DB/Qdrant optional check 付きに拡張 or `/ready` を別途。worker/bot のログ末尾検査。
    **OI-26（Discord通知）の実装**で可視化。関連: OI-26 / CLAUDE.md「CD」節。

- **OI-50（P2）: 正式な schema migration が無い**
  - 指摘: `src/db.py init_schema()` は `CREATE TABLE IF NOT EXISTS`。新規テーブルには強いが、既存テーブルの
    カラム追加・型/index 変更が将来つらい。memories/consent_log/billing/Stripe/mimic 等を増やすなら要検討。
  - 対応案: Alembic か軽量 `schema_migrations` テーブル導入。既存DBからの移行手順を docs/ に。CIで
    旧schema fixture からの migration も検査。関連: OI-14 D / OI-43。

- **OI-51（P2）: config.yml と config.yml.example の運用ドリフト**
  - 指摘: ローカル `config.yml`（ignored）が `config.yml.example` より項目が少ない（history_max_turns/
    history_max_chars/rewriter_history_*/debug_trace/search_gate/reranker/contextualizer retry 等）。
    コード側 default があり即バグではないが「今どの設定が効くか」が不透明。
  - 対応案: ローカル config を最新 example に追随。`docs/CONFIG.md`＋`config.yml.example` を正典に。
    起動時に主要設定をログ出力。関連: docs/CONFIG.md。

**codex-fugu 推奨の着手順:** OI-44（purge範囲）→ OI-45（API認証）→ OI-46（/remember quota・管理導線）
→ OI-48（同意ログ）→ OI-49（CD後チェック＋OI-26）。この5つで「身内ベータ→公開/課金の手前」まで安全度が上がる。

### OI-52〜54: OI整理で発見した未起票の運用・技術的負債（2026-06-22・未着手）

このセッションのOI棚卸し（コード/DEVLOG横断スキャン）で見つかった、既存OIに載っていない項目。
いずれも P2 以下の housekeeping だが、放置すると効いてくるので記録する。

- **OI-52（P2）: GitFlow の `main` 不整合・リリースフロー未整備**
  - 現状: `origin/main` は **`Initial commit` 1件のみ**で、`develop` が **472コミット先行**。GitFlow を
    掲げているが develop が全てを持ち、main へリリースが一度も流れていない。CD は develop 起点で
    回っている（CLAUDE.md「CD」節）ため稼働はするが、**「公開＝mainが本番」という運用に切り替える際に
    main が空のままだと事故る**（タグ/リリース/ロールバック基点が無い）。DEVLOG 2026-06-18 に
    「develop → main のリリース整理（main は別ルートの空のため要対応）」と既記。
  - 対応案: develop を main へ初回リリースとして取り込む方針を決める（merge or main を develop に
    リセットして接ぎ直す＝履歴方針は人間判断）。以降のリリースタグ運用・CDのデプロイ基点（develop のままか
    main に移すか）を明文化。あわせて**マージ済みローカル feature ブランチ**（feature/waiwai-oracle /
    multitenant-ingest / saas-rag-engine / usage-metering-portal / oi18-mention-resolution 等）の掃除。
  - 関連: OI-14 E（インフラ・本番化）/ CLAUDE.md「Git運用ルール」「CD」。

- **OI-53（P2）: テストの非決定的な揺らぎ（test_db / test_indexer の分離）**
  - 現状: `pytest-randomly` のランダム順序で **test_db 同士の分離揺らぎ**で稀に1件 error、
    **test_indexer のインメモリQdrant共有**でも稀に揺れる（DEVLOG 2026-06 / CLAUDE.md に
    「CIクリーン環境では再現せずパス・コードのバグではない」と既記）。複数箇所に分散していて OI が無い。
  - 対応案: テスト間の状態分離を堅くする（test_db は per-test TRUNCATE/トランザクション境界の見直し、
    test_indexer はインメモリQdrant共有をやめ fixture でテストごとに分離）。CIで `-p randomly` を明示し
    seed を固定/記録して再現性を確保。優先度は低い（CIは緑）。
  - 関連: CLAUDE.md「CI」節 / `feedback_test_db_tmpfs`。

- **OI-54（P3）: 既知の軽微なランタイム/依存ドリフト**
  - 現状: ①`src/api.py:201` の `@app.on_event("startup")` は **FastAPI で deprecated**（将来 lifespan へ
    移行が必要）。②ローカル `.venv` が **Python 3.9.6**（README/CI/Docker は **3.11+**）でズレ。
    ③urllib3+LibreSSL 警告。いずれも codex-fugu レビュー（OI-44〜51）の警告欄で既出だが、独立した
    対応項目として未整理。
  - 対応案: ①startup/shutdown を `lifespan` ハンドラへ移行（admin 側も確認）。②ローカル venv を 3.11+ に
    そろえる（運用手順 or `.python-version`）。③は影響軽微・様子見。
  - 関連: OI-51（config ドリフト）/ CLAUDE.md「技術スタック」。

---

## OI-44〜49: コードレビュー指摘（2026-06-22・セキュリティ/プライバシー/運用）

`develop`（HEAD `7be5957` 付近）に対する軽量レビューで挙がった指摘群。**いずれも未着手**で、
着手＝ソース変更・方針決定の前には必ず人間に確認する（OI-14 と同じ流儀）。テストは現状
217 passed / 151 skipped（DB依存はローカルPostgresがなくCI側で実行される）。

**優先度サマリ（推奨）:**
- **最優先（公開前に必須）**: OI-44（退出時の全削除が不完全）/ OI-45（API無認証・guild_id偽装）。
- **高**: OI-46（`/remember` がquota管理外）/ OI-47（明示メモリの安全弁不足）/ OI-48（同意ログ未実装）。
- **中**: OI-49（CD後ヘルスチェックがAPIのみ）。

### OI-44: Bot退出/purge時の「全削除」が不完全（最優先・プライバシー）
- **症状**: README/規約のニュアンス（Bot退出で `guild_id` データを全削除）と実装が不整合。
  [src/db.py](../src/db.py) の `purge_guild_data()` は `attachments`/`messages`/`chunk_index`/
  `crawl_state`/`allowed_channels` のみ削除し、**`memories`/`usage_log`/`chat_trace`/`guild_plans`/
  `ingest_jobs`/`run_log` が残る**。特に `memories`・`chat_trace` はユーザー発話・本文・ヒットチャンクを
  含みうるため「全削除」と言い切れない。
- **対応案（要確認・まだ実装しない）**:
  - `purge_guild_data()` の削除対象に少なくとも `memories`・`chat_trace` を追加。
  - 会計監査で残したい `usage_log`/`guild_plans` は「保持する／本文・user_id を匿名化する」の
    どちらにするか方針決定し、規約/READMEの表現と一致させる。
  - [tests/test_db.py](../tests/test_db.py) に削除/保持ポリシーの検証を追加。
- **関連**: OI-24（memories）/ OI-21（chat_trace）/ OI-14 A（法務・削除権）/ OI-11（退出時削除）。

### OI-45: `/chat`・`/remember` が無認証で `guild_id` がクライアント指定（最優先・セキュリティ）
- **症状**: [src/api.py](../src/api.py) はリクエストの `guild_id` をそのまま検索に使い、Botからの
  呼び出しを検証する認証/署名が無い。かつ [docker-compose.yml](../docker-compose.yml) で API を
  `8000:8000` でホスト公開している。外部到達可能な配置になると、他 `guild_id` 指定で別サーバー文脈の
  検索・quota消費・LLMコスト発生のリスク。
- **対応案（要確認・まだ実装しない）**:
  - Bot→API間に共有シークレット（例: `X-Oracle-Token`）を入れ、API側で検証する。
  - 本番は API/admin の公開範囲を Tailscale/VPN/内部ネットワークに限定（compose のポート公開見直し）。
  - 将来の公開時は gateway/auth/rate-limit を別途検討。
- **関連**: OI-14 C-2（quota）/ OI-14 E（インフラ・公開面）。

### OI-46: `/remember` が quota/レート管理の外でコスト発生（高）
- **症状**: 質問上限は `/chat` 入口で見ているが、[src/api.py](../src/api.py) の `/remember` は
  quotaチェック無しで LLM 抽出を実行する。さらに [src/db.py](../src/db.py) の
  `count_questions_since()` は `kind='answer'` しか数えないため、「覚えておいて」連打で
  **コストだけ増え・上限にも乗らず・memories が汚染される**抜け道になる。
- **対応案（要確認・まだ実装しない）**:
  - `/remember` も quota/レート制限の対象にする（guild/user/channel 単位の短時間レート制限など）。
  - 明示メモリ書き込みを管理者限定 or モデレーション可能にする。
  - `/oracle memory list|delete` 的な管理導線を用意する。
- **関連**: OI-24（memories）/ OI-14 C-2（quota）/ OI-47。

### OI-47: 明示メモリが有効だが安全弁が薄い（高）
- **症状**: [config.yml](../config.yml) は `rag.memory_enabled: true`。誰でもサーバー全体の長期記憶を
  書け、センシティブ属性/個人情報/虚偽情報の保存ガードが弱い。回答時に memories を**全件注入**するため
  件数増でプロンプトが肥大化する。削除/一覧/監査UIも未整備。
- **対応案（要確認・まだ実装しない）**:
  - memories に moderation status を持たせる／承認制 or 信頼ユーザー限定。
  - 件数上限・古い記憶の要約・関連memoryだけ検索注入（全件注入の見直し）。
  - 管理ポータルに memory 管理画面を追加。
  - 退出/purge時に memories を削除（OI-44 と連動）。
- **関連**: OI-24（memories）/ OI-36（プロファイル・プライバシー）/ OI-14 A。

### OI-48: 公開/課金前の同意ログが未実装（高・法務）
- **症状**: `/oracle allow` は opt-in 設計だが、現状のBot文面（`_WELCOME`/`allow` 応答）は
  「過去ログ本文の保存」「外部LLM APIへの送信」「料金/quota/削除ポリシー」への明示同意ログまでは
  取っていない。公開・有料化には事実上必須（OI-14 A）。
- **対応案（要確認・まだ実装しない）**:
  - `/oracle allow`/`allowall` 初回に同意文を表示し、同意した管理者ID・日時・対象ch・規約バージョンを
    `consent_log`（新テーブル）に保存。
  - `allowall` は全ch対象のため、より強い確認フローにする。
- **関連**: OI-14 A（法務）/ OI-25（allowall）/ OI-11（opt-in）。

### OI-49: CD後のヘルスチェックがAPIのみ（中・運用）
- **症状**: [.github/workflows/tests.yml](../.github/workflows/tests.yml) の `deploy` は
  `git reset --hard origin/develop` + `docker compose up -d --build` 後に API `/health` だけ確認する。
  bot/worker/admin の死活・DB/Qdrant 実接続・実際の `/chat` 動作・ジョブ処理が落ちていても成功扱いになる。
- **対応案（要確認・まだ実装しない）**:
  - compose に `healthcheck`/`restart: unless-stopped` を追加、CD後に `docker compose ps` を検査。
  - `/health` を DB/Qdrant の任意チェック付きに拡張、または `/ready` を別途用意。
  - worker/bot のログ末尾検査と、OI-26（Discordデプロイ通知）の実装。
- **関連**: OI-26（デプロイ通知）/ OI-13（取り込み完了通知）/ OI-14 E（運用）。

補足（番号化はしないが記録）: スキーマは `CREATE TABLE IF NOT EXISTS` 運用で正式な migration が無く、
今後の列追加・型変更に備え Alembic 等の導入余地あり。ローカル `config.yml` が `config.yml.example` より
項目が少なく（history/debug_trace/search_gate/reranker 等）、現行設定の見通しが悪い点も要追従。

---

## OI-27: オンボーディング `/oracle help`（使い方ヘルプ）（対応済み）

**対応:** `/oracle help` を追加（[bot.py](../moimoichan_Discordbot/bot.py) の `_HELP` 定数）。
導入フロー（allow/allowall → sync → メンションで質問）・主要コマンド一覧・管理ポータル案内を
静的テキストで返す（ephemeral）。テストは [tests/test_bot_help.py](../tests/test_bot_help.py)。

**背景:** 現状ユーザーが使い方を知る手段は、Botのサーバー参加時に1回だけ流れる welcome
メッセージ（[bot.py](../moimoichan_Discordbot/bot.py) の `_WELCOME`）しかない。後から
「どう質問するの？」「どう許可するの？」を確認する導線が無く、新規メンバーや後から入った
管理者がコマンドや質問方法に辿り着けない。一般的なDiscord Botにはあるヘルプを追加する。

**スコープ（このフェーズ）:**
- `/oracle help`（引数なし・**誰でも実行可**にする＝管理コマンドの allow/deny 等と違い権限不要）を追加。
  - 注意: 既存の `OracleGroup` は `default_permissions=manage_guild` でグループ全体に管理権限が
    かかっている。help は一般ユーザーにも見せたいので、**権限要件の扱いを要検討**
    （別グループにする／コマンド単位で権限を上書きする／`/help` をトップレベルコマンドにする等）。
- 内容（ephemeral で返す想定・チャンネルを汚さない）:
  - 質問のしかた（@メンションで話しかける／設定によりトリガーチャンネル限定の旨）
  - 「覚えておいて」で事実を記憶できること（OI-24）
  - 管理者向け: `/oracle allow|allowall|deny|sync|status` の早見表（権限が必要な旨も明記）
  - れみちゃんの口調・キャラに合わせた文面にする（`_WELCOME` と同じトーン）
- 文面は `bot.py` 内の定数（`_WELCOME` の隣に `_HELP` 等）に切り出すと welcome と一貫性を保てる。

**実装の当たり所:**
- `moimoichan_Discordbot/bot.py`: コマンド定義（`OracleGroup` か新規トップレベルコマンド）。
- テスト: Bot のコマンドは Discord 依存で単体テストしづらいので、**文面定数の組み立てを純粋関数に
  切り出して** テストする（メッセージに主要コマンド名が含まれること等）か、最小に留める。
- 反映には **bot コンテナの再ビルド**が必要（`docker compose up -d --build bot`）。

**残・要確認(人間):** ヘルプを ephemeral にするか全員に見える形にするか、管理コマンドを
一般ユーザーにも一覧表示してよいか（権限なしユーザーには実行できないだけで一覧は見せる想定）。
関連: OI-25（allowall）/ OI-24（覚えておいて）/ welcome メッセージ（`_WELCOME`）

## OI-26: CDデプロイ完了をDiscordに通知する（未着手）

**背景:** 2026-06-20 に CD を導入（`develop` マージ → pytest 緑 → `remember-vm` へ自動デプロイ・
[.github/workflows/tests.yml](../.github/workflows/tests.yml) の `deploy` ジョブ / PR #29）。
現状デプロイの成否は **GitHub の Actions 画面でしか分からない**。マージしたら Discord に
「デプロイ成功 ✅ / 失敗 ❌（コミットSHA・所要時間・/health 結果）」を流したい。

**実装アイデア（着手時に要検討・まだ実装しない）:**
- 最小: `deploy` ジョブの末尾に Discord Webhook へ `curl` で1回 POST するステップを足す
  （成功時）＋ `if: failure()` の通知ステップ（失敗時）。Webhook URL は GitHub Secrets に置く。
  - self-hosted runner は VM 上（Tailnet 内）だが **外向き443は開いている**ので Webhook POST は通る。
  - メッセージに `${{ github.sha }}` / コミットメッセージ / ジョブ結果を載せる。
- 既存の通知系（OI-13 取り込み完了通知）とは**別物**。あちらはワーカー→ユーザー通知、
  こちらは CI/CD →運用者向け（管理用チャンネル/サポートサーバー想定）。
- Webhook を使うか、Bot の常駐接続を使うかは要検討（Webhook が一番手軽・runner から独立）。

**要確認(人間):** 通知先チャンネル、成功も通知するか失敗だけにするか、メッセージ書式。
関連: OI-13（取り込み完了通知）/ CD（CLAUDE.md「CD（自動デプロイ）」節）

## OI-25: 全チャンネル一括許可コマンド `/oracle allowall`（MAXプラン限定）✅ 実装完了（feature/oi25-allow-all）

**背景:** チャンネル数が多いサーバーで全チャンネルを取り込むには `/oracle allow #ch` を
1つずつ実行する必要があり手間だった。MAXプラン（チャンネル数無制限）の利用者向けに
**全テキストチャンネルを一括許可する**コマンドを追加する。

**実装方式（既存の opt-in / quota 機構に乗せる・OI-14 C-2 と整合）:**
- Discord のスラッシュコマンドは `allow` が必須のチャンネル引数を持つため `allow all` という
  文字列指定はできない。**別サブコマンド `/oracle allowall`（引数なし）**として実装。
- `moimoichan_Discordbot/bot.py`: `OracleGroup.allowall` を追加。Botが**閲覧＋履歴読み取り**
  できる全テキストチャンネルだけを対象に集めて Store へ渡す（権限の無いchはクロール不可のため除外）。
- `moimoichan_Discordbot/store.py`: `Store.allow_all_channels()` を追加。
  プランの `channel_limit` が **None（無制限＝MAX）のときだけ許可**。それ以外は拒否して案内文を返す。
  既許可chはスキップし、新規許可があれば取り込みジョブ（`JOB_INGEST`）を1件だけ投入。
  ※ワーカーは1ジョブで guild の全許可chをクロールする設計なので、ジョブは1件で十分。
- `src/quota.py`: `allow_all_allowed(channel_limit)`（None=MAXのみTrue）と
  `allow_all_denied_message()`（MAX限定の案内文）を追加。**MAX判定は plan_key ハードコードでなく
  `channel_limit is None`（無制限）で行う**（plan_defs はDB編集可なので将来の無制限プランも自然に対象）。
- テスト: `tests/test_store.py` 新規（実DBで MAX許可/free・pro拒否/既許可スキップ/部分追加）＋
  `tests/test_quota.py` に allowall 判定・案内文を追加。

**残・要確認(人間):**
- 一括許可は**同意フロー（OI-14 A の規約同意）を個別 allow と同じ粒度で持たない**。公開・有料化時に
  「全ch一括取り込み」の同意取得をどう見せるか要検討。
- 取り込みコストはチャンネル数に比例。MAXは上限満杯でも黒字設計（OI-14 C-2）だが、巨大サーバーの
  初回一括取り込みは contextualizer/embedding が一時的に重い。
- 関連: OI-14 C-2（quota・プラン）/ OI-11（opt-in 取り込み）

## OI-23: 検索ゲート（必要なければベクトル検索をスキップ）✅ 実装完了（2026-06-19・feature/oi23-search-gate）

「じゃんけんしよう！」「こんにちは」「今日の天気は？」のような**過去ログ参照が不要な雑談・
ゲーム・一般質問**でも、従来は必ず embedding→Qdrant検索→（リランク）が走り、かつ回答プロンプトが
記憶前提に固定されていたため「ん〜それは覚えてないかも〜」と不自然に断る劣化があった。

### 採った方式（agentic RAG の軽量版 = 事前ルーター）
Remember は tool-use 構成ではない（Rewriter→検索→回答の固定パイプ）ため、フルなツール化ではなく
**Query Rewriter に検索要否判定を兼務させる**のが最小改修。既存の Rewriter LLM 呼び出しに相乗り＝
**追加コスト・追加レイテンシ ゼロ**。
- `src/rag/prompts.py`: Rewriter に「過去ログ参照が不要なら `[NO_SEARCH]` だけ返す」ルール0を追加
  （**迷ったら必ず検索**に倒す）。回答プロンプトにも「過去ログと無関係な入力は記憶に絡めず素で応じる」
  方針を追加（①）。`NO_SEARCH_SENTINEL` / `SKIP_CONTEXT` 定数。
- `src/rag/engine.py`: rewrite結果に `[NO_SEARCH]` が含まれたら埋め込み・検索・リランクをスキップし、
  `{context}` に `SKIP_CONTEXT` を入れて回答。`rag.search_gate`（既定True）で無効化可。
  戻り値に `search_skipped` を追加。トレースは `rewritten_query` に `[NO_SEARCH]` が残るので判別可能。

### A/Bテスト結果（実Qdrant31チャンク・雑談6+記憶6問・LLMジャッジ gemini-2.5-flash）
`scripts/ab_search_skip.py` で Baseline / ①プロンプト改善 / ②①+検索スキップ を比較:
| | 雑談スコア | 雑談レイテンシ | 雑談コスト/1k | 記憶スコア | 誤スキップ |
|---|---|---|---|---|---|
| Baseline | 3.17 | 8183ms | $3.14 | 5.00 | — |
| ①プロンプト | 4.00 | 5644ms | $3.15 | 5.00 | — |
| ②①+スキップ | 4.33 | 4345ms | $0.46 | 4.83 | **0/6** |

- ①で雑談が改善（記憶は無傷）、②でさらに雑談コスト約85%減・レイテンシ47%減。
- **最大リスクの「記憶質問の誤スキップ」は 0/6 で発生せず**（全記憶質問で正しく検索）。
  記憶4.83はジャッジ揺れ（②も正しく検索・具体回答）。
- 注意: 「今日の天気は？」は全バリアントで1点＝**天気を知る手段（ツール）が無い別課題**。
  検索スキップでは直らない（→ OI-17 のツール化と関連）。

### 残し / 今後
- 関連: OI-17（function calling ツール化＝本格的な agentic RAG。本件はその軽量先取り）/ OI-16（コスト）/ OI-15（プロンプト）
- `scripts/ab_search_skip.py` は再評価用に残置（生データ `ab_results.json` はプライバシー上コミットしない）。
- 本番反映後、chat_trace（OI-21）で `[NO_SEARCH]` の誤判定（記憶質問をスキップ／雑談を検索）を継続監視する。

## OI-9: 検索品質（リランキング / ハイブリッド）

旧Difyフローはキーワード0.6/ベクトル0.4のハイブリッド検索 + Jinaリランカーだった。

### ✅ Phase 1: リランカー実装済み（2026-06-17・feature/oi9-reranker）
方式は「dense で多めに取って cross-encoder で精選」（Direction A）。日本語に強く・既存データの
再インデックス不要・OI-16のコスト方針（多く取って絞る）と整合するため、BM25ハイブリッドより先に採用。
- `src/rag/reranker.py`: Jina Reranker クライアント（`jina-reranker-v2-base-multilingual`）。
- `src/rag/engine.py`: `rag.reranker.enabled` の時のみ、dense `top_n`(既定30) → リランクで `top_k` に精選。
  失敗・キー未設定時は dense 順にフォールバック（回答は止めない）。usage_log に `rerank` を記録。
- **既定オフ**（`enabled: false`）。有効化には `.env` の `JINA_API_KEY` ＋ `config.yml rag.reranker.enabled: true`。

#### 実データA/B結果 → **本番有効化は見送り（既定OFF維持）**（2026-06-19）
GCP検証機の実テスト鯖（guild `1462079315045908567`・約560点）に対し、Discordで実際に投げた
質問から検索ヘビーな5問を選び、`scripts/ab_rerank_test.py`（コンテナ版）で **dense上位5 vs
リランク後5** を比較した。
- リランクは候補集合を大きく変える（5中4〜5が入れ替わる）が、**回答品質は明確に向上しなかった**。
- 「ほしのかなた」では dense が拾えていた的確なチャンク（BOOTHで欲しがってた話）を**リランクが落として
  回答が曖昧化＝むしろ悪化**。他もdense同等以上。リランク採用チャンクはdenseスコアが軒並み低い。
- **結論**: Jina v2 multilingual はこの日本語カジュアルチャット＋これらのクエリでは費用対効果が見合わない
  （品質ゲイン無し vs Jina APIコスト・レイテンシ・外部依存の増加）。**本番では有効化しない**。
- 今回の品質改善の主レバーは**プロンプトv4（OI-15）**で達成済み（曖昧化指示の撤廃）。
- 再検討の余地: top_n/top_k やリランク投入テキスト（context_text込み）のチューニング、別リランカー、
  Phase 2（BM25ハイブリッド）。ただし**burden of proofはリランク側**＝明確な改善が示せたときだけ採用する。

### ⬜ Phase 2: スパース(BM25)ハイブリッドは見送り中
Qdrant native の sparse+dense 融合(RRF)は追加API課金ゼロだが、**日本語のBM25分かち書きが弱い**・
全チャンク**再インデックス**が必要。Phase 1 のリランクで品質が足りなければ再検討する。

## OI-21: 回答のデバッグトレース（質問・ヒットチャンク・回答のログ）✅ 実装完了（2026-06-19・feature/chat-trace-logging）

**背景:** 検索品質や回答の A/B、回答が外した原因の追跡をしたくても、**実際に投げた質問・
検索でヒットしたチャンク・出力した回答が一切残っていなかった**（usage_log はトークン/コストの
メトリクスのみ・APIログはアクセスログのみ・Bot履歴はメモリ揮発）。OI-9 リランカー A/B の
質問セットを実チャンクから推測する羽目になり、観測性の欠如が顕在化した。

**実装方式（usage_log と同じ流儀・既定OFF）:**
- `chat_trace` テーブル新設（question / rewritten_query / answer / sources(JSONB・本文含む) /
  model / rerank_enabled / tokens / cost_usd / latency_ms）。詳細は `docs/SCHEMA.md`。
- `src/trace.py` の `TraceRecorder`（`UsageRecorder` の双子）が `src/db.py insert_trace` で書き込み。
  `src/rag/engine.py answer()` が1リクエスト分を `asyncio.to_thread` 経由で記録。
- **既定オフ**。`config.yml rag.debug_trace: true` のときだけ記録（`build_engine` と engine の二重ガード）。
  記録失敗は回答を止めない（DB障害時でも /chat は動く）。
- テスト +10件（engine 5 / db 2 / api 3・全315 PASS）。

**残・要確認(人間):**
- **プライバシー**: 質問・回答本文・チャンク本文を平文保存する。公開/本番では false 運用が前提
  （規約・OI-14 A と整合させる）。将来 guild 単位 DB トグル（plan_defs 流）や保持期間・自動purgeも検討。
- 管理ポータル `src/admin/` への閲覧画面は未実装（今は SQL で参照）。必要になれば追加。
- 関連: OI-9（リランカー A/B）/ OI-16（コスト）/ OI-14 A（法務）

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
- ✅ **C-2（quota/上限）実装済み（feature/oi14-c2-quota・2026-06-18）**:
  - 料金プラン確定: **Free ¥0/1ch/20問・日**、**Pro ¥700/10ch/80問・日**、**MAX ¥1500/全ch/200問・日**
    （他AI Discord botの相場 $5〜$20/サーバーの範囲内）。超過時は**ハードストップ＋翌日リセット＋
    アップグレード案内**（全プラン）。
  - **プラン定義はDB管理**（`plan_defs` テーブル・ポータル `/billing` から編集可・ハードコードなし）。
    サーバー割当は `guild_plans`（無い=free / Stripe列は D 用に予約）。
  - 強制: 質問の日次上限は `src/api.py` `/chat` 入口（`src/quota.py`・超過は回答せず案内＝コスト0）、
    チャンネル数上限は Bot `/oracle allow`（`store.py`）。日次境界は JST 0時。
  - プラン切替は**手動**（ポータル）。自動化は OI-14 D（Stripe Webhook で `guild_plans` 更新）。
  - 実コスト実測 ≈ ¥0.2/問（OI-16後）なので全プラン上限満杯でも赤字にならない設計。
  - テスト: quota/db_plans/api を追加（健全DB時 C-2新規37件含め全PASS）。
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

### v4（情報量回復・2026-06-19・feature/prompt-v4-informative）

v3「れみちゃん」リブランド後、**回答が過度に曖昧・短く・タスク拒否がち**になり体感精度が落ちた
（ユーザー所感）。chat_trace（OI-21）に貯めた**実トレースの同一検索結果**で v3 vs v4 をA/B
（`scripts/ab_prompt_test.py`）した結果、v4 が明確に改善:
- 「優しい人ランキング上位5」: v3=**拒否**「やだな〜」→ v4=具体的エピソード付きで5人列挙
- 人物の性格/紹介: v3=ぼんやり → v4=発言を引用し具体的に
- れみの口調・絵文字・ゆるさは維持（情報量だけ回復）

**変更点（`src/rag/prompts.py ANSWER_SYSTEM_PROMPT`）:**
- 「不確かなことは曖昧にして伝える」「できるだけ短く」を撤廃 → 覚えていることは具体的に・本当に
  うろ覚えのときだけ控えめに
- ランキング・要約・比較などの依頼にも記憶を根拠に応じる（最初から断らない）
- 履歴 `prompts/v4_remi_informative.md` 追加・`prompts/README.md` 更新
- 反映には api / bot 再ビルドが必要（`docker compose up -d --build api bot`）

**残・要確認(人間):**
- **センシティブ属性のガードレールは未実装（今回は見送り・検証機優先）**。v4 は「ゲイな人ランキング」等、
  個人の性的指向・健康などを実名で序列化する依頼にも答えるようになった。**公開・有料化の前に OI-14 A（法務）で
  対応方針を決める**（例: センシティブ属性の序列化・暴露を断るガードレール文を追加）。
- A/B は単一ターン中心（chat_trace は history を保存しないため、マルチターン質問は履歴なしで比較）。

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

## OI-22: 回答LLMに「いま話しかけている人」の名前を渡す ✅ 実装完了（2026-06-19・feature/oi22-speaker-name）

**背景:** Bot に @メンションで質問しても、回答LLMには**質問文だけ**が届いており、
**発言者（話しかけてきた本人）の名前を一切認識していなかった**。Bot→API へ渡すのは
`query`/`guild_id`/`user`（数値ID・usage集計用）/`guild_name`/`history` のみで、
回答プロンプト（`ANSWER_SYSTEM_PROMPT`）にも発言者名の差し込み口が無かった。
このため「わたしのこと覚えてる？」「○○って呼んで」のような本人を指す発話を解釈できず、
名前で呼びかけることもできなかった（過去ログ側のチャンクには発言者名が入っているが、
それは検索対象＝他者の記録であって、今まさに話している人とは別物）。

**実装方式（history と同じく呼び出し側が渡すステートレス設計・任意）:**
- `src/rag/prompts.py`: `SPEAKER_SECTION`（「いま話しかけてくれている人」ブロック）を新設し、
  `ANSWER_SYSTEM_PROMPT` に `{speaker_section}` プレースホルダを追加。
- `src/rag/engine.py`: `answer()` に `speaker_name`（任意）を追加。値があればブロックを差し込み、
  未指定・空白なら**ブロックごと空文字に置換して消す**（CLI 等は従来どおり）。
- `src/api.py`: `ChatRequest.speaker` を追加し `answer()` の `speaker_name` へ素通し。
- `moimoichan_Discordbot/`: `oracle_client.chat()` に `speaker` を追加（payload に載せる）。
  `bot.py` が `message.author.display_name`（crawler の保存名と同じ＝サーバーニックネーム優先）を渡す。
- `chat_cli.py`: 変更不要（speaker 省略＝ブロック非表示）。
- テスト +4件（engine 3：差し込み/未指定で消える/空白扱い・api 1：素通し）。既存 api テストの
  タプル比較を6要素へ更新。

**反映:** プロンプト・APIの変更につき **api / bot コンテナの再ビルド**が必要
（`docker compose up -d --build api bot`）。

**残・将来の選択肢(任意):**
- 今回は**回答プロンプトのみ**に注入。「わたしが前に言ってたやつ」を**検索**で当てたい場合は
  Query Rewriter にも speaker を渡して名前で具体化する余地がある（クエリ汚染リスクとのトレードオフ）。
- 表示名は guild ニックネーム優先のため、改名すると過去ログ側の名前と食い違うことがある。
- 関連: OI-18（`<@ID>`→表示名解決）/ OI-17（ツール使用の代替）/ OI-10（呼び出し側ステートレス設計）

## OI-24: 明示メモリ機能（「覚えておいて」）✅ 読み取り＋書き込み実装・A/B完了（PR #27）

> 注: OI-23 は別ブランチ（`feature/oi23-search-gate`・検索要否ゲート）が先に使用中のため、
> 本件は OI-24 として採番した。

**背景:** 現状 remember は **Discord過去ログのRAG** しか記憶源を持たない。ユーザーが
「3/25は誕生日だよ、覚えておいて」「かにじるはケーキが好き」のように **明示的に教えた事実**を
覚えておく仕組みが無い。これは ChatGPT/Claude の「メモリ」機能に相当し、プロダクト名
`remember` の核にもなり得る。一般的なチャットLLMの定石は「会話ログそのものでなく **短い独立した
fact** に整形して別領域に保持し、回答時にプロンプトへ注入」「ユーザーが一覧・削除できる」。
過去ログとは別の記憶領域に持つ、という当初の直感は正しい。

**設計判断:** **本当にベクトルDBが要るかは件数次第**（メモリは数十〜数百件程度。少数なら
Postgres に全件持って丸ごと注入する方が確実・シンプル＝ChatGPT も少数なら全部 system prompt に
入れる）。そこで **まず最小実装（Postgres保存＋プロンプト注入）して「メモリあり/なし」で回答が
良くなるか**を A/B で確かめ、効果が確認できてから書き込みUI・（必要なら）Qdrant化へ進む。
- A/B構成 = **効果だけ先に（なし vs あり）**。保存先は **Postgres 全件注入**で固定。
- 書き込みUI（本実装フェーズ）= **「覚えておいて」検知**（A/B後に着手）。
- A/B実行 = ローカル（実行直前にAPIコスト規模を提示して最終GO）。

**このフェーズのスコープ（読み取り経路の最小実装＋使い捨てA/B）:**
- `memories` テーブル新設（`src/db.py`・`guild_id / subject / content / created_by /
  source_channel_id / created_at`・embedding列なし＝全件注入）。詳細は `docs/SCHEMA.md`。
- ヘルパー: `insert_memory` / `fetch_memories` / `delete_memory` / `count_memories`。
- `src/rag/prompts.py`: `MEMORY_SECTION`（「## みんなから教わって覚えていること」＝過去ログの
  うろ覚え `## 記憶` とは別の**はっきり教わった事実**）＋ `ANSWER_SYSTEM_PROMPT` に
  `{taught_memories}` プレースホルダ＋ `build_memories()`。
- `src/rag/engine.py`: `memory_provider`（usage_recorder と同じ注入）＋ `rag.memory_enabled`
  （**既定OFF**）。`answer()` が guild の memories を取得し注入。無効・空・取得失敗時はブロックごと
  消す（回答は止めない）。`src/api.py build_engine` が config フラグで配線。
- 使い捨て A/B `scripts/ab_memory.py`: baseline（注入なし）vs mem（教わった事実を全件注入）を
  記憶系/対照系の質問で LLM ジャッジ比較（既存 `ab_search_skip.py` 流儀）。

**実装済み（PR #27・読み取り＋書き込み）:**
- ✅ 読み取り経路: `memories` テーブル / 全件プロンプト注入 / `rag.memory_enabled`（既定OFF）。
- ✅ **「覚えておいて」検知**（書き込みUI）: Bot `on_message`（メンション＋フレーズ検知）→ API
  `POST /remember` → LLM抽出（`extract_memory`・subject/content）→ `insert_memory`。
  誤爆は LLM が null 判定で弾く（下記A/B）。保存結果はBotが「覚えたよ！」と返信。

**残・後段:**
- 管理/削除: `/oracle forget`、admin ポータルでの一覧・削除（プライバシー・GDPR削除権と整合）。
- 更新 vs 追記（「誕生日3/25」→「3/26」）の上書き戦略。
- Qdrant化: 全件注入が重くなったら別コレクション＋ベクトル検索へ。
- 関連: OI-10（呼び出し側ステートレス設計）/ OI-22（speaker）/ OI-21（trace）/ OI-14 A（法務・プライバシー）

### A/B結果（2026-06-19・ローカル実行）→ **効果明確。書き込みUI・本番化に進む価値あり**

`scripts/ab_memory.py`（本番 RagEngine をそのまま使用・base=注入なし / mem=教わった事実3件を
全件注入）を実データ guild（`1464840187061338317`・31チャンク）に対しローカル実行。LLMジャッジ
（gemini-2.5-flash）で記憶系/対照系を別軸採点。

| カテゴリ | base（注入なし） | mem（注入あり） |
|---|---|---|
| 記憶系（3問・教わった事実に答えるべき） | **1.00** | **5.00** |
| 対照系（3問・過去ログ質問／記憶は無関係） | 4.67 | **5.00** |
| コスト | 記憶系 ≈$0.0027/問・対照系 ≈$0.0013/問 | ほぼ同じ（+0.6〜3%＝誤差。memories3件のため） |

- **記憶系は全滅→満点**: base は「覚えてないや〜」と答えるか、**幻覚**（「ゲーム会＝毎週金曜の夜」と
  もっともらしく誤答）。mem は「ケーキが好き」「誕生日3月25日」「ゲーム会＝毎週日曜の夜」と正答。
  → 明示メモリは**回答可能性だけでなく幻覚の矯正**にも効く。
- **対照系は劣化なし**（むしろ微増）: 注入した事実を無関係な質問に持ち出して脱線する事象は起きず、
  過去ログ質問に普通に答えた（ジャッジ理由も全件「脱線なし」）。
- コスト増は誤差。ただし memories 件数が増えれば全件注入は線形に効くので、数百件規模になったら
  Qdrant化（関連メモリのみ検索注入）を再検討する。
- 結論: **読み取り経路（Postgres全件注入）は採用してよい**。次は書き込みUI（「覚えておいて」検知）の実装。

### A/B結果（書き込み・抽出／2026-06-19・ローカル実行）→ **LLM抽出を採用**

`scripts/ab_memory_extract.py`（本番 `extract_memory`[LLM抽出] vs 素朴保存[フレーズ除去のみ・null判定なし]）を、
SHOULD（記憶すべき4発話）/ NOISE（「覚えておいて」を含むが記憶不要な4発話）で LLM ジャッジ比較。

| | LLM抽出（本実装） | 素朴保存 |
|---|---|---|
| SHOULD 抽出品質（5満点） | **5.00** | 2.00（主語を落とし冗長） |
| NOISE 誤爆（保存してしまった件数／4件中） | **0/4** | 4/4（全件誤保存） |

- LLM抽出は subject/content を的確に構造化し、NOISE は**全件 null 判定で保存を見送った**（誤爆ゼロ）。
- 素朴保存は SHOULD で主語を取れず冗長、NOISE は4件すべて誤爆保存。
- 結論: **LLM抽出（本実装）を採用**。誤爆制御が決定的に優れる。抽出は安価な Gemini Flash で1発話 ≈ $0.0002。

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
