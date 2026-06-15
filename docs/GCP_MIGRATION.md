# GCP移行 runbook（ベータ・初心者向け・セキュア構成）

OI-14 E の実作業手順。**GCP初心者が安全に辿れること**を最優先に書く。
迷ったら「公開しない・最小権限・まず予算アラート」を思い出す。

## 前提（2026-06-15 決定）

- **目的**: 収益化の必須条件としてベータ期間中に GCP へ移行する。
- **構成**: lift-and-shift（今の `docker compose` をほぼそのまま単一 VM に載せる）。
  将来 Cloud SQL 等へ段階的にマネージド化する。
- **予算**: 月 **$20 以下**。VM は **e2-small**（2GB RAM）/ リージョン **asia-northeast1（東京）**。
- **アクセス**: **Tailscale 経由のみ**。管理ポータル・Postgres・Qdrant・SSH は Tailscale 内限定。
  **インターネットに開けるインバウンドポートは作らない**（Bot は外向き接続のみで動く）。

### なぜこの構成が安全か
Discord Bot は Discord へ**繋ぎに行く**（アウトバウンド）だけで、外から入る口が要らない。
api/admin は VM 内部通信、管理画面は自分が Tailscale で入る。
→ 公開IPに何も晒さない＝攻撃面がほぼゼロ。GCP初心者が最も事故りにくい。

### AWS との対応（少しAWSを触ったことがある人向け）
| AWS | GCP | 用途 |
|---|---|---|
| EC2 | GCE（VM インスタンス） | サーバー本体 |
| Security Group | VPC ファイアウォール | ポート制御 |
| Secrets Manager | Secret Manager | APIキー保管 |
| IAM | IAM | 権限 |
| EBS スナップショット | ディスクスナップショット | バックアップ |
| CloudWatch | Cloud Monitoring | 監視 |
| 請求アラート | 予算（Budgets）アラート | 課金事故防止 |

---

## Phase 0: アカウント・請求・安全柵（★最初に必ず・人間が操作）

> GCP初心者の最大リスクは**請求事故**。VMを作る前に予算アラートを必ず設定する。

1. **Googleアカウントに2段階認証(MFA)を有効化**（収益化アカウントの大前提）。
2. https://console.cloud.google.com/ で**請求先アカウント**を作成（クレカ登録）。
   - 無料トライアル（$300クレジット/90日）が使えれば、ベータ期間はほぼ無料。
3. **プロジェクト作成**（例: `remember-beta`）。プロジェクトIDを控える。
4. **予算アラートを設定**（Billing → 予算とアラート → 予算を作成）:
   - 予算額: **$20/月**
   - しきい値アラート: **50% / 90% / 100%**（メール通知ON）
   - ※GCPの予算は「自動停止」ではなく**通知**。上限超過で自動的にVMは止まらない点に注意。
     完全停止が要るなら、Pub/Sub + Cloud Functions で課金停止を組む（ベータでは通知で十分）。
5. **使わないAPIは有効化しない**（最小化）。今回必要なのは Compute Engine API のみ（Phase 1で有効化）。

✅ Phase 0 完了条件: MFA済み / 請求アカウント有効 / プロジェクト作成済み / **$20予算アラート設定済み**。

---

## Phase 1: VM 作成（最小・公開ポートなし）

1. Compute Engine API を有効化。
2. VM インスタンス作成:
   - 名前: `remember-vm`
   - リージョン/ゾーン: `asia-northeast1`（東京）/ `asia-northeast1-a`
   - マシンタイプ: **e2-small**（2GB RAM・月 ≈ $13-15）
   - ブートディスク: **Debian 12** / 標準永続ディスク **30GB**（≈ $1.2/月）
   - **ファイアウォール: 「HTTPトラフィックを許可」「HTTPSトラフィックを許可」は両方OFF**
     （公開しないため。Tailscale はアウトバウンドで繋がるので開放不要）
3. サービスアカウント: 既定のまま（後で Secret Manager 用に最小ロールだけ付与）。

> RAM 2GB に Postgres+Qdrant+api+admin+worker+bot を同居させるので、Phase 3 で **swap 2GB** を作る。
> もし動作が重い/OOMする場合は e2-medium（4GB・≈$27/月）に上げる（予算は要再相談）。

✅ Phase 1 完了条件: VM が起動し、公開ファイアウォール規則が無いこと。

---

## Phase 2: Tailscale 参加（これでアクセス経路を確保）

1. VM に一度だけブラウザSSH（コンソールの「SSH」ボタン）で入る。
2. Tailscale を入れて参加:
   ```sh
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --ssh
   ```
   - `--ssh` で **Tailscale SSH** が有効になり、以後 SSH も Tailscale 経由でできる。
3. 自分のPCの Tailscale から VM の Tailscale IP / MagicDNS 名で到達できることを確認。
4. （任意・推奨）GCPの**外部IPを削除**して完全内向きに。アウトバウンドだけなら Cloud NAT を使う
   （ベータでは外部IPありのままでも、ファイアウォールでインバウンド0なら実用上安全）。

✅ Phase 2 完了条件: Tailscale 経由で VM に SSH でき、公開ポート無し。

---

## Phase 3: Docker + アプリ配置 + 機密管理

1. Docker / Docker Compose を導入（Debian公式手順）。swap作成:
   ```sh
   sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
   sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```
2. リポジトリを配置（git clone）。
3. **機密情報の扱い**（2段階）:
   - ベータ初期: `.env` を VM 上に置く（パーミッション 600・Tailscale内のみアクセス）。
   - 推奨: **Secret Manager** に APIキー/トークンを保管し、起動時に取得して環境変数へ。
     VM のサービスアカウントに `roles/secretmanager.secretAccessor` だけ付与（最小権限）。
4. `docker compose up -d`（compose のポート公開は `127.0.0.1` バインドにして、外向きに出さない）。
   - 管理ポータル(8001)・api(8000) は **VM内 or Tailscale からのみ**到達させる。

✅ Phase 3 完了条件: Tailscale から `http://<vm>:8001/login` に入れ、`/health` がOK。

---

## Phase 4: データ移行

> waiwai 旧データは「もう使わない」方針。テストサーバーのデータも少量。
> **ベータは新規再取り込みで始めるのが最も簡単**（移行不要）。必要なら以下で移行する。

- Postgres: Mac側で `pg_dump` → VM側 `psql` でリストア。
- Qdrant: コレクションのスナップショットを取得 → VM側で復元。または `indexer.py --all` で再生成。

✅ Phase 4 完了条件: 管理ポータルでサーバー/チャンク数が期待通り表示される。

---

## Phase 5: バックアップ・監視

- **バックアップ**: ディスクの**スナップショットスケジュール**（日次・保持7日など）を設定。
- **監視**: 公開エンドポイントが無いので、VM内 cron で `/health` を叩いて失敗時に通知、
  or Cloud Monitoring の ops agent でメモリ/CPU/ディスクアラート。
- 月次で GCP請求 + LLM API費を突き合わせ、OI-14 C の収益と損益分岐を確認。

✅ Phase 5 完了条件: 自動バックアップ稼働 / 異常時に自分へ通知が届く。

---

## Phase 6: 段階的マネージド化（収益化が見えてきたら）

- Postgres → **Cloud SQL for PostgreSQL**（自動バックアップ・パッチ・HA）。
- api/admin → **Cloud Run**（ステートレス・自動スケール）。Bot/worker は常駐なので VM/GKE 継続。
- TLS が要る場合（ポータルを社外公開する等）はマネージド証明書 + ロードバランサ。

---

## 困ったとき・原則
- 「公開しないといけない気がする」→ たいてい不要。まず Tailscale で足りないか考える。
- 「権限エラー」→ 足りない**最小ロール**だけ足す（オーナー権限を安易に付けない）。
- 「請求が不安」→ Billing の予算アラート と 課金レポートを見る。VMは使わない時は**停止**で課金が止まる
  （ディスク代だけ残る）。
