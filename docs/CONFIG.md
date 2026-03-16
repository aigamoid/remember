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
  window_before: 2           # アンカーの前N件
  window_after: 2            # アンカーの後N件
  min_content_length: 10     # これ未満の文字数メッセージはスキップ

dify:
  api_endpoint: "http://<DifyホストIP>/v1"

ollama:
  endpoint: "http://<TailscaleIP>:11434"
  embed_model: "bge-m3"
```

## .env

```env
DISCORD_TOKEN=your-discord-bot-token
DIFY_API_KEY=your-dify-api-key
```

## 分離ルール

| 種別 | ファイル | Gitコミット |
|---|---|---|
| 動作パラメータ | config.yml | ✅ OK |
| APIキー・トークン | .env | ❌ 必ずgitignore |

## Docker環境での読み込み

- `config.yml` → コンテナ内 `/app/config.yml` にマウント
- `.env` → `docker-compose.yml` の `env_file` で読み込み
