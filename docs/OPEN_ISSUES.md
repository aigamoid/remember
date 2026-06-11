# 未解決事項・TODO

## OI-9: ハイブリッド検索・リランキング未実装（Dify比で検索構成が簡素化）

旧Difyフローはキーワード0.6/ベクトル0.4のハイブリッド検索 + Jinaリランカーだったが、
自前RAGエンジン（2026-06-11移行）はベクトル検索のみ（top_k=10）。
日本語キーワード検索の品質はDify側も怪しかったため一旦純ベクトルで運用し、
検索精度に不満が出たら Qdrant のスパースベクトル（BM25系）+ リランカー追加を検討する。

## OI-10: 会話履歴（マルチターン）非対応

自前API化に伴い conversation_id を廃止（DEVLOG 2026-03-25 の「無効化プラン」を実施）。
現状は1問1答。マルチターンが必要になったら Bot 側で直近の会話を API に渡す設計を検討。

## ~~OI-11: SaaS化ステップ2（マルチテナント自動取り込み）~~ ✅ 実装完了 (2026-06-11)

feature/multitenant-ingest で実装。
- SQLite → Postgres 移行（psycopg / 全テーブル guild_id 対応 / `scripts/migrate_sqlite_to_pg.py` で既存データ移行済み）
- ingest_jobs ジョブキュー + 常駐ワーカー（worker.py）: allow/sync/定期24h で
  クロール→チャンク→文脈付与→インデックスを自動実行
- 管理者向けスラッシュコマンド `/oracle allow|deny|sync|status`（opt-in方式）
- deny / Bot退出時のデータ削除（Qdrant + Postgres の purge）
- 残り: 実機E2E（→OI-12）、Discord Bot検証・Message Content Intent 審査（100サーバー以上で必要。99までは不要）

## OI-12: マルチテナント取り込みの実機E2E未実施

実装・ユニットテスト（211件）は完了したが、実際のDiscordサーバーでの動作確認が未実施。
必要なもの:
- Discordトークンの再発行（旧トークンは無効化済み）
- テスト用Discordサーバー（waiwaiサーバーへのアクセスは禁止方針）
- 確認項目: on_guild_join 挨拶 / スラッシュコマンド同期 / allow→自動取り込み→@メンション回答 /
  deny→データ削除 / Bot退出→purge_guild

## OI-13: 取り込み完了のDiscord通知が無い

ワーカーはジョブ完了を ingest_jobs.result に記録するだけで、Discordへ通知しない
（ワーカーはgateway接続を持たない設計のため）。現状は `/oracle status` で確認する運用。
必要になったら: Bot側でジョブ完了をポーリングして通知する or ワーカーにwebhook URLを渡す。

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
