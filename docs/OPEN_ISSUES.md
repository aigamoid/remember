# 未解決事項・TODO

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

## OI-3: ThreadCollector 未実装
現在はTextChannelのみ取得。スレッド対応は将来実装。
`collectors/base.py` のABCは拡張を前提に設計済み。

## ~~OI-4: Discord Message Content Intent 確認~~ ✅ 完了 (2026-03-15)
MESSAGE CONTENT INTENT がONになっていることを確認済み。

## OI-5: Dify Knowledge APIのチャンク数上限確認
Difyバージョンによってナレッジベースのドキュメント数上限が異なる。
dry_run.py実行後、チャンク数見積もりと照合すること。

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
- uploader.py 側でメタデータフィルタ設定が不要になり実装が簡素化される
