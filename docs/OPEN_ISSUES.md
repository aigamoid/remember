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
