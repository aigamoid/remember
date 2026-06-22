#!/usr/bin/env python3
"""旧 docs/OPEN_ISSUES.md の未着手OIを GitHub Issues へ移行する一回限りの冪等スクリプト。

- manifest(docs/oi_migration.tsv)に作成済みIssueを記録し、再実行しても重複作成しない。
- アイデア群(OI-28〜43)は「魅力強化 epic」1本に集約。OI-14 は収益化ロードマップ epic。
- OI-45〜49 は旧ファイルで codex-fugu版とコードレビュー版に重複していたため統合して起票。
- 2026-06-22 の OI管理 GitHub Issues 移行（CLAUDE.md「Git運用ルール」参照）。
"""
import csv
import os
import subprocess
import sys

REPO = "aigamoid/waiwai-oracle"
MANIFEST = "docs/oi_migration.tsv"
FOOTER = (
    "\n\n---\n*このIssueは旧 `docs/OPEN_ISSUES.md` からの移行（2026-06-22）。"
    "コード内の旧OI番号参照は本Issueを指す（対応表は `docs/OPEN_ISSUES.md` のインデックス表）。*"
)

# merged=True のものは codex-fugu版とコードレビュー版が重複していた指摘
ISSUES = [
    {
        "oi": "OI-14",
        "title": "OI-14: 収益化・パブリック化ロードマップ（epic）",
        "labels": ["P1", "area:infra-ops", "kind:feature"],
        "body": """## 概要（epic）
このBotを一般公開（パブリックBot化）し、サブスクで収益化することを目標とする親Issue。
技術基盤（マルチテナント分離・opt-in取り込み・退出時データ削除）は OI-11 で完成済み。
残るは **法務・Discord審査・コスト管理・課金・インフラ**。

## 進める順番（推奨）
1. OI-12（実機E2E）✅完了 ← 公開の大前提
2. 法務(A) + Discord審査(B)（コード不要・並行着手可）
3. コスト計測(C) ← 課金の前提
4. 課金(D) ← Cの後
5. インフラ(E) ← 顧客が付き始めてから本格化

## 領域
- **A. 法務**（最優先・任意ではない）: 本文保存＋第三者LLM送信のため規約明示が事実上必須。Discord審査でも提出を求められる。
- **B. Discord審査**: パブリックBot申請。
- **C. コスト/quota計測**: 課金の前提（C-2 quota）。
- **D. 課金**: Stripe等。
- **E. インフラ**: 本番化・公開面。
- **F. 管理ポータル**: ✅初版実装済み。

## 子Issue（具体化）
- 公開手前の安全性: OI-44 / OI-45 / OI-46 / OI-47 / OI-48
- インフラ/運用: OI-49 / OI-50 / OI-52

詳細（A〜Fの全文）は旧 `docs/OPEN_ISSUES.md` の git 履歴を参照。""",
    },
    {
        "oi": "OI-28-43",
        "title": "OI-28〜43: 魅力強化（リテンション・課金理由）アイデア群（epic）",
        "labels": ["area:retention", "kind:idea"],
        "body": """## 概要（epic・アイデア段階）
収益化に向け「お金を注ぎ込みたくなる魅力の核」を増す案を集約。**いずれもアイデア段階**で、
着手＝ソース変更・方針決定の前には必ず人間に確認する。OI-14（収益化ロードマップ）の横断アイデア。

**コンセプト転換:** 「聞かれたら答える検索ツール」→「コミュニティの共有記憶を持つ"れみちゃんという一員"」
（そこに居て・覚えていて・自分から思い出させる存在）。空いた陣地＝"コミュニティの共有脳"が堀。

**市場調査3類型:** ①ゲーミフィケーション/エンゲージ ②AIの人格・記憶・愛着 ③キャッチアップ/要約。
教訓: MEE6は過度な収益化で評判を落とした（出し惜しみは毒）/ Discordが要約を公式実装（単純機能はコモディティ化）。

## アイデア一覧
- **高（中核）**: OI-29 記憶ベースのパーソナライズド・クエスト（最有力）/ OI-28 関係性が育つメーター / OI-33 プッシュ型「思い出し」
- **中**: OI-30 スケジュール配信ダイジェスト（＋記憶差別化）/ OI-32 「知識を教えると育つ」貢献エコノミー / OI-31 サーバーごと人格カスタム / OI-35 管理者が育てる公式FAQ / OI-36 メンバープロファイルカード / OI-37 記憶の"育つ"可視化
- **要検討（低）**: OI-34 オンデマンド要約（Discord公式と競合・記憶連携で差別化できる時のみ）
- **Codex追加アイデア**: OI-38 Memory Moments / OI-39 Quest Streak / OI-40 Server Memory Capsule（月次レポート）/ OI-41 Proactive Warm Ping / OI-42 Admin Copilot Pack
- **高（愛着/話題性）**: OI-43 「真似っこ」モード（OI-36×OI-31 の合体・メンバーを憑依させる）

## 進め方
実装順推奨: OI-29 → OI-33 → OI-28/OI-37。まず OI-29 を MVP で小さく検証。
スパム化防止（頻度上限・quiet hours・opt-out）を初期から。追うKPI: 7日/28日継続率・DAU/WAU・転換率・ミュート率。

各アイデアの詳細・着想元（市場調査リンク）は旧 `docs/OPEN_ISSUES.md` の git 履歴を参照。""",
    },
    {
        "oi": "OI-3",
        "title": "OI-3: ThreadCollector 未実装（スレッド取得）",
        "labels": ["P3", "area:bot", "kind:feature"],
        "body": """## 概要
現在は TextChannel のみ取得。スレッド対応は将来実装。
`collectors/base.py` の ABC は拡張を前提に設計済み。""",
    },
    {
        "oi": "OI-13",
        "title": "OI-13: 取り込み完了のDiscord通知が無い",
        "labels": ["P2", "area:bot", "kind:feature"],
        "body": """## 症状
ワーカーはジョブ完了を `ingest_jobs.result` に記録するだけで、Discordへ通知しない
（ワーカーは gateway 接続を持たない設計のため）。現状は `/oracle status` で確認する運用。

## 対応案
Bot側でジョブ完了をポーリングして通知する、またはワーカーに webhook URL を渡す。

## 関連
OI-26（CDデプロイ通知）— あちらは CI/CD→運用者向け、本件はワーカー→ユーザー向けで別物。""",
    },
    {
        "oi": "OI-19",
        "title": "OI-19: worker の `Event loop is closed` 警告（無害・既知）",
        "labels": ["P3", "area:infra-ops", "kind:tech-debt"],
        "body": """## 症状
取り込み中、worker ログに `RuntimeError: Event loop is closed`
（`Task exception was never retrieved` / httpx `AsyncClient.aclose()` 由来）が散発（60分で3回）。

## 影響
**なし**: 全ジョブ done・`error_message` 空、chunk_index 件数と Qdrant ベクトル数も一致（543=543）。
終了時の後始末ログのノイズ。

## 原因（推定）・対応
ジョブごとに asyncio ループを回す際、非同期HTTPクライアントを明示クローズせず GC時にループ閉鎖後の `aclose()` が走る。
急がない。検証が一段落したら根本対応（明示 `aclose()` / ループを跨がない作り）。放置するとログに常駐し本物のエラーを埋もれさせるので、いずれ潰す。""",
    },
    {
        "oi": "OI-26",
        "title": "OI-26: CDデプロイ完了をDiscordに通知する",
        "labels": ["P2", "area:infra-ops", "kind:feature"],
        "body": """## 背景
2026-06-20 に CD を導入（develop マージ → pytest 緑 → remember-vm へ自動デプロイ）。
現状デプロイの成否は GitHub Actions 画面でしか分からない。Discord に
「デプロイ成功 ✅ / 失敗 ❌（コミットSHA・所要時間・/health 結果）」を流したい。

## 実装アイデア（着手時に要検討）
- 最小: `deploy` ジョブ末尾に Discord Webhook へ `curl` で POST（成功時）＋ `if: failure()` 通知（失敗時）。Webhook URL は GitHub Secrets。
- self-hosted runner は Tailnet 内だが外向き443は開いているので Webhook POST は通る。
- Webhook か Bot 常駐接続かは要検討（Webhook が手軽・runner から独立）。

## 要確認（人間）
通知先チャンネル、成功も通知するか失敗だけか、メッセージ書式。

## 関連
OI-13（取り込み完了通知・別系統）/ CD（CLAUDE.md「CD」節）/ OI-49（CD後チェック）""",
    },
    {
        "oi": "OI-45",
        "title": "OI-45: /chat・/remember が無認証で guild_id がクライアント指定",
        "labels": ["P0", "area:security-privacy", "kind:tech-debt"],
        "merged": True,
        "body": """## 症状
`src/api.py` の `/chat` はリクエストの `guild_id` をそのまま検索に使い、Bot発であることを検証する認証/署名が無い。
かつ `docker-compose.yml` で API を `8000:8000` でホスト公開している。外部到達可能な配置だと、
他 `guild_id` 指定で別サーバー文脈の検索・quota消費・LLMコスト発生のリスク。

## 対応案（着手前に人間確認）
- Bot→API 間に共有シークレット（例 `X-Oracle-Token`）を入れ、API側で guild_id と bot-origin を検証。
- 本番は API/admin の公開範囲を Tailscale/VPN/内部網に限定（compose のポート公開見直し）。
- 将来の公開時は gateway/auth/rate-limit を別途検討。

## 関連
OI-14 E（インフラ・公開面）/ OI-46""",
    },
    {
        "oi": "OI-46",
        "title": "OI-46: /remember が quota/レート管理の外でコスト発生・記憶汚染",
        "labels": ["P1", "area:security-privacy", "kind:tech-debt"],
        "merged": True,
        "body": """## 症状
質問上限は `/chat` 入口で見ているが、`/remember` は quota チェック無しで LLM 抽出を実行する。
さらに `count_questions_since()` は `kind='answer'` しか数えないため、「覚えておいて」連打で
**コストだけ増え・上限にも乗らず・memories が汚染される**抜け道になる。

## 対応案（着手前に人間確認）
- `/remember` も quota/レート制限の対象にする（guild/user/channel 単位の短時間レート制限など）。
- 明示メモリ書き込みを管理者限定 or モデレーション可能にする。
- `/oracle memory list|delete` 的な管理導線を用意する。

## 関連
OI-24（memories）/ OI-14 C-2（quota）/ OI-47""",
    },
    {
        "oi": "OI-47",
        "title": "OI-47: 明示メモリが有効だが安全弁が薄い",
        "labels": ["P1", "area:security-privacy", "kind:tech-debt"],
        "merged": True,
        "body": """## 症状
`config.yml` は `rag.memory_enabled: true`。誰でもサーバー全体の長期記憶を書け、
センシティブ属性/個人情報/虚偽情報の保存ガードが弱い。回答時に memories を**全件注入**するため
件数増でプロンプトが肥大化する。削除/一覧/監査UIも未整備。

## 対応案（着手前に人間確認）
- memories に moderation status を持たせる／承認制 or 信頼ユーザー限定。
- 件数上限・古い記憶の要約・関連memoryだけ検索注入（全件注入の見直し）。
- 管理ポータルに memory 管理画面を追加。
- 退出/purge時に memories を削除（OI-44 と連動）。

## 関連
OI-24（memories）/ OI-36（プロファイル・プライバシー）/ OI-14 A / OI-44""",
    },
    {
        "oi": "OI-48",
        "title": "OI-48: 公開/課金前の同意ログが未実装（法務）",
        "labels": ["P1", "area:security-privacy", "kind:tech-debt"],
        "merged": True,
        "body": """## 症状
`/oracle allow` は opt-in 設計だが、現状の Bot 文面は
「過去ログ本文の保存」「外部LLM APIへの送信」「料金/quota/削除ポリシー」への明示同意ログまでは取っていない。
公開・有料化には事実上必須（OI-14 A）。

## 対応案（着手前に人間確認）
- `/oracle allow`/`allowall` 初回に同意文を表示し、同意した管理者ID・日時・対象ch・規約バージョンを
  `consent_log`（新テーブル）に保存。
- `allowall` は全ch対象のため、より強い確認フローにする。

## 関連
OI-14 A（法務）/ OI-25（allowall）/ OI-11（opt-in）""",
    },
    {
        "oi": "OI-49",
        "title": "OI-49: CD後のヘルスチェックがAPIのみ",
        "labels": ["P2", "area:infra-ops", "kind:tech-debt"],
        "merged": True,
        "body": """## 症状
CD の `deploy` は `git reset --hard origin/develop` + `docker compose up -d --build` 後に
API `/health` だけ確認する。bot/worker/admin の死活・DB/Qdrant 実接続・実 `/chat` 動作・
ジョブ処理が落ちていても成功扱いになりうる。

## 対応案（着手前に人間確認）
- compose に `healthcheck`/`restart: unless-stopped` を追加、CD後に `docker compose ps` を検査。
- `/health` を DB/Qdrant の任意チェック付きに拡張、または `/ready` を別途用意。
- worker/bot のログ末尾検査と、OI-26（Discordデプロイ通知）の実装。

## 関連
OI-26（デプロイ通知）/ OI-13（取り込み完了通知）/ OI-14 E（運用）""",
    },
    {
        "oi": "OI-50",
        "title": "OI-50: 正式な schema migration が無い",
        "labels": ["P2", "area:infra-ops", "kind:tech-debt"],
        "body": """## 症状
`src/db.py init_schema()` は `CREATE TABLE IF NOT EXISTS`。新規テーブルには強いが、
既存テーブルのカラム追加・型/index 変更が将来つらい。memories/consent_log/billing/Stripe/mimic 等を増やすなら要検討。

## 対応案
Alembic か軽量 `schema_migrations` テーブル導入。既存DBからの移行手順を docs/ に。
CI で旧 schema fixture からの migration も検査。

## 関連
OI-14 D / OI-43""",
    },
    {
        "oi": "OI-51",
        "title": "OI-51: config.yml と config.yml.example の運用ドリフト",
        "labels": ["P2", "area:infra-ops", "kind:tech-debt"],
        "body": """## 症状
ローカル `config.yml`（ignored）が `config.yml.example` より項目が少ない
（history_max_turns/history_max_chars/rewriter_history_*/debug_trace/search_gate/reranker/contextualizer retry 等）。
コード側 default があり即バグではないが「今どの設定が効くか」が不透明。

## 対応案
ローカル config を最新 example に追随。`docs/CONFIG.md`＋`config.yml.example` を正典に。
起動時に主要設定をログ出力。

## 関連
docs/CONFIG.md""",
    },
    {
        "oi": "OI-52",
        "title": "OI-52: GitFlow の main 不整合・リリースフロー未整備",
        "labels": ["P2", "area:infra-ops", "kind:tech-debt"],
        "body": """## 症状
`origin/main` は `Initial commit` 1件のみで、`develop` が大きく先行。GitFlow を掲げているが
develop が全てを持ち、main へリリースが一度も流れていない。CD は develop 起点で回っているため稼働はするが、
**「公開＝main が本番」という運用に切り替える際に main が空のままだと事故る**
（タグ/リリース/ロールバック基点が無い）。

## 対応案
develop を main へ初回リリースとして取り込む方針を決める（履歴方針は人間判断）。
以降のリリースタグ運用・CDのデプロイ基点を明文化。あわせてマージ済みローカル feature ブランチを掃除。

## 関連
OI-14 E（本番化）/ CLAUDE.md「Git運用ルール」「CD」""",
    },
    {
        "oi": "OI-53",
        "title": "OI-53: テストの非決定的な揺らぎ（test_db / test_indexer の分離）",
        "labels": ["P2", "area:infra-ops", "kind:tech-debt"],
        "body": """## 症状
`pytest-randomly` のランダム順序で test_db 同士の分離揺らぎで稀に1件 error、
test_indexer のインメモリQdrant共有でも稀に揺れる
（CIクリーン環境では再現せずパス・コードのバグではない）。

## 対応案
テスト間の状態分離を堅くする（test_db は per-test TRUNCATE/トランザクション境界の見直し、
test_indexer はインメモリQdrant共有をやめ fixture でテストごとに分離）。
CI で `-p randomly` を明示し seed を固定/記録して再現性を確保。優先度は低い（CIは緑）。

## 関連
CLAUDE.md「CI」節 / feedback_test_db_tmpfs""",
    },
    {
        "oi": "OI-54",
        "title": "OI-54: 既知の軽微なランタイム/依存ドリフト",
        "labels": ["P3", "area:infra-ops", "kind:tech-debt"],
        "body": """## 症状
- ① `src/api.py` の `@app.on_event("startup")` は FastAPI で deprecated（将来 lifespan へ移行が必要）。
- ② ローカル `.venv` が Python 3.9.6（README/CI/Docker は 3.11+）でズレ。
- ③ urllib3+LibreSSL 警告。

## 対応案
- ① startup/shutdown を `lifespan` ハンドラへ移行（admin 側も確認）。
- ② ローカル venv を 3.11+ にそろえる（運用手順 or `.python-version`）。
- ③ 影響軽微・様子見。

## 関連
OI-51（config ドリフト）/ CLAUDE.md「技術スタック」""",
    },
]


def load_done():
    done = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if row.get("issue", "").startswith("#"):
                    done[row["oi"]] = row["issue"]
    return done


def append_manifest(oi, title, labels, issue):
    new = not os.path.exists(MANIFEST)
    with open(MANIFEST, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        if new:
            w.writerow(["oi", "title", "labels", "issue", "status"])
        w.writerow([oi, title, ",".join(labels), issue, "created"])


def make_body(item):
    oi = item["oi"]
    head = (
        f"> **Legacy-ID:** {oi}\n"
        f"> **Source:** `docs/OPEN_ISSUES.md`（2026-06-22 に GitHub Issues へ移行）\n"
    )
    if item.get("merged"):
        head += (
            f"> **統合:** 旧 `docs/OPEN_ISSUES.md` に同一指摘が2件あった"
            f"（codex-fugu 安全性レビュー版 {oi} ＋ コードレビュー指摘版 {oi}）。同一内容のため本Issueへ統合。\n"
        )
    return head + "\n" + item["body"] + FOOTER


def main():
    done = load_done()
    for item in ISSUES:
        oi = item["oi"]
        if oi in done:
            print(f"skip {oi} (already {done[oi]})")
            continue
        body = make_body(item)
        cmd = ["gh", "issue", "create", "--repo", REPO,
               "--title", item["title"], "--body", body]
        for lb in item["labels"]:
            cmd += ["--label", lb]
        try:
            out = subprocess.check_output(cmd, text=True).strip()
        except subprocess.CalledProcessError as e:
            print(f"ERROR creating {oi}: {e}", file=sys.stderr)
            sys.exit(1)
        num = "#" + out.rstrip("/").split("/")[-1]
        append_manifest(oi, item["title"], item["labels"], num)
        print(f"created {oi} -> {num}  {out}")


if __name__ == "__main__":
    main()
