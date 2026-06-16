#!/usr/bin/env bash
# GCP Secret Manager から .env を生成する（GCP VM上でのデプロイ時に docker compose up の前に実行）。
#
# 仕組み: VMのサービスアカウントのアクセストークンをメタデータサーバーから取得し、
#         Secret Manager REST API で各シークレットを読む（VMに gcloud 不要・鍵ファイル不要）。
# 前提:   VMのSAに各シークレットの secretmanager.secretAccessor 付与済み（GCP側で設定済み）。
# 使い方: bash scripts/load_secrets_from_gcp.sh   （省略時 ~/remember/.env を生成）
set -euo pipefail

PROJECT="remember-beta-2606812"
ENV_FILE="${1:-$HOME/remember/.env}"
META="http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"

_token() {
  curl -s -H "Metadata-Flavor: Google" "$META" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}

TOKEN="$(_token)"
[ -n "$TOKEN" ] || { echo "ERROR: アクセストークン取得失敗（GCP VM上で実行していますか？）" >&2; exit 1; }

get() {  # $1 = secret名 → 値を標準出力（base64デコード）
  curl -s -H "Authorization: Bearer $TOKEN" \
    "https://secretmanager.googleapis.com/v1/projects/$PROJECT/secrets/$1/versions/latest:access" \
    | python3 -c 'import sys,json,base64;print(base64.b64decode(json.load(sys.stdin)["payload"]["data"]).decode(),end="")'
}

umask 077  # 生成ファイルは 600
{
  printf 'DISCORD_TOKEN=%s\n'      "$(get discord-token)"
  printf 'OPENAI_API_KEY=%s\n'     "$(get openai-api-key)"
  printf 'OPENROUTER_API_KEY=%s\n' "$(get openrouter-api-key)"
  printf 'ADMIN_PASSWORD=%s\n'     "$(get admin-password)"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "OK: $ENV_FILE を Secret Manager から生成（$(wc -l < "$ENV_FILE") 行）"
