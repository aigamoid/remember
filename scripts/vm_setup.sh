#!/usr/bin/env bash
# GCP VM(Debian 12)の初期セットアップ: Docker + Compose プラグイン + swap。
# Phase 3 で VM 上で一度だけ実行する（docs/GCP_MIGRATION.md 参照）。
set -euo pipefail

echo "=== 1) swap 2GB 作成（e2-small の RAM 不足対策） ==="
if ! sudo swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  echo "swap 作成完了"
else
  echo "swap は既に有効"
fi

echo "=== 2) Docker 公式リポジトリ追加 ==="
sudo apt-get update -qq
sudo apt-get install -y -qq ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "=== 3) Docker 本体 + compose プラグイン導入 ==="
sudo apt-get update -qq
sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "=== 4) 自分を docker グループへ（次回ログインから sudo 不要に） ==="
sudo usermod -aG docker "$USER"

echo "=== 確認 ==="
sudo docker --version
sudo docker compose version
free -h | sed -n '1,3p'
echo "=== VM セットアップ完了 ==="
