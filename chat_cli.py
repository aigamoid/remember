#!/usr/bin/env python3
"""
chat_cli.py - RAG APIに質問するCLIフロントエンド（動作確認用）

実行方法:
    python chat_cli.py                      # config.yml の guild_id を使用
    python chat_cli.py --guild-id 12345
    python chat_cli.py --api-url http://localhost:8000

前提: docker compose up -d qdrant api でAPIサーバが起動していること。
Discord Bot と同じ POST /chat を使うため、CLIで動けばBotのバックエンドも動く。
"""

import argparse
import os
import sys

import requests
from dotenv import load_dotenv

from src.cli import chat_once, check_health, format_result
from src.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG APIに質問するCLI")
    parser.add_argument(
        "--api-url",
        default=None,
        help="APIサーバURL（既定: $ORACLE_API_URL または http://localhost:8000）",
    )
    parser.add_argument(
        "--guild-id",
        default=None,
        help="guild ID（既定: config.yml の guild_id）",
    )
    args = parser.parse_args()

    load_dotenv()
    api_url = (
        args.api_url or os.getenv("ORACLE_API_URL") or "http://localhost:8000"
    )
    api_token = os.getenv("ORACLE_API_TOKEN")
    guild_id = args.guild_id or str(load_config().get("guild_id", ""))
    if not guild_id:
        print("エラー: guild_id が特定できません（--guild-id か config.yml で指定）")
        sys.exit(1)

    if not check_health(api_url):
        print(f"エラー: APIサーバに接続できません: {api_url}")
        print("docker compose up -d qdrant api で起動してください")
        sys.exit(1)

    print(f"remember CLI（API: {api_url} / guild: {guild_id}）")
    print("質問を入力してください（exit / quit / Ctrl-D で終了, reset で会話履歴クリア）")

    # 直近の会話履歴（マルチターン・OI-10）。古い順 {"role","content"} のリスト。
    history: list[dict] = []
    history_max_turns = 5  # 直近5ペアまで送る（engine 側でも丸められる）

    while True:
        try:
            query = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nバイバイ！っ 👋")
            break
        if not query:
            continue
        if query.lower() in ("exit", "quit"):
            print("バイバイ！っ 👋")
            break
        if query.lower() == "reset":
            history.clear()
            print("（会話履歴をクリアしたよ！っ）")
            continue

        print("（考え中…）")
        try:
            result = chat_once(
                api_url, guild_id, query, history=history, api_token=api_token
            )
            print(format_result(result))
            # 今回のやり取りを履歴に追加し、直近 N ペアに丸める。
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": result.get("answer", "")})
            del history[: -history_max_turns * 2]
        except requests.RequestException as e:
            print(f"⚠️ APIエラー: {e}")


if __name__ == "__main__":
    main()
