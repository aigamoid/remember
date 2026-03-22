# 設定ファイル仕様

## config.yml

```yaml
guild_id: 123456789          # 対象DiscordサーバーのID

crawl:
  exclude_channels:          # 除外チャンネル名リスト
    - bot-log
    - spam
  exclude_channel_ids:       # IDでの除外（名前変更に強い）
    - 987654321

chunk:
  time_gap_minutes: 60       # N分以上の間隔があればチャンク境界（会話スレッド単位）
  max_chunk_messages: 30     # 1チャンクに含める最大メッセージ数
  min_content_length: 10     # これ未満の文字数メッセージはスキップ
  timezone_offset: 9         # タイムスタンプ表示のUTCオフセット（JST=9）

ollama:
  endpoint: "http://<TailscaleIP>:11434"
  embed_model: "bge-m3"
```

## .env

```env
DISCORD_TOKEN=your-discord-bot-token
```

## 分離ルール

| 種別 | ファイル | Gitコミット |
|---|---|---|
| 動作パラメータ | config.yml | ✅ OK |
| APIキー・トークン | .env | ❌ 必ずgitignore |

## Docker環境での読み込み

- `config.yml` → コンテナ内 `/app/config.yml` にマウント
- `.env` → `docker-compose.yml` の `env_file` で読み込み
