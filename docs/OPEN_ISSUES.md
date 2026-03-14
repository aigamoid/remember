# 未解決事項・TODO

## OI-1: dry_run.py 未実行
対象サーバーのメッセージ総数が未確定。
crawler.py着手前に必ず実行してチャンク数・アップロード量を見積もること。

```bash
docker compose run oracle python dry_run.py
```

## OI-2: Dify未インストール
Windows 5090機にDifyをインストールする必要がある。
インストール後に以下を設定すること：
- Embedding Model: Ollama / bge-m3
- Ollama endpoint: http://<TailscaleIP>:11434
- dataset_idをconfig.ymlに記載

## OI-3: ThreadCollector 未実装
現在はTextChannelのみ取得。スレッド対応は将来実装。
`collectors/base.py` のABCは拡張を前提に設計済み。

## OI-4: Discord Message Content Intent 確認
Developer Portal → Bot → Privileged Gateway Intents
→ MESSAGE CONTENT INTENT がONになっているか確認すること。
OFFだとメッセージ本文が空文字で返る。

## OI-5: Dify Knowledge APIのチャンク数上限確認
Difyバージョンによってナレッジベースのドキュメント数上限が異なる。
dry_run.py実行後、チャンク数見積もりと照合すること。
