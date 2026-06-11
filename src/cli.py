"""CLIチャットロジック。chat_cli.py から使用。

RAG APIサーバ（src/api.py）の POST /chat を呼ぶ薄いクライアント。
Discord Bot（moimoichan_Discordbot/）と同じAPIを使う動作確認用フロントエンド。
"""

from __future__ import annotations

import time

import requests


def check_health(api_url: str, timeout: int = 5) -> bool:
    """APIサーバの /health に接続できるか確認する。"""
    try:
        resp = requests.get(f"{api_url.rstrip('/')}/health", timeout=timeout)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def chat_once(
    api_url: str, guild_id: str, query: str, timeout: int = 120
) -> dict:
    """1問送信して応答辞書を返す。経過秒数を elapsed キーに追加する。

    Raises:
        requests.RequestException: 接続失敗・HTTP 4xx/5xx
    """
    started = time.time()
    resp = requests.post(
        f"{api_url.rstrip('/')}/chat",
        json={"guild_id": str(guild_id), "query": query, "user": "cli"},
        timeout=timeout,
    )
    resp.raise_for_status()
    result = resp.json()
    result["elapsed"] = time.time() - started
    return result


def format_result(result: dict) -> str:
    """応答を表示用テキストに整形する（書き換えクエリ・回答・ソース・時間）。"""
    lines = []
    rewritten = result.get("rewritten_query", "")
    if rewritten:
        lines.append(f"🔎 検索クエリ: {rewritten}")
        lines.append("")
    lines.append(result.get("answer", ""))
    lines.append("")

    sources = result.get("sources") or []
    # 重複を除いたチャンネル名（出現順を保持）
    channels = list(
        dict.fromkeys(s.get("channel_name") or "?" for s in sources)
    )
    footer = f"（ソース {len(sources)} 件"
    if channels:
        footer += ": " + ", ".join(channels[:5])
    elapsed = result.get("elapsed")
    if elapsed is not None:
        footer += f" / {elapsed:.1f}秒"
    footer += "）"
    lines.append(footer)
    return "\n".join(lines)
