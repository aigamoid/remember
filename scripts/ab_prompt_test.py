"""プロンプトA/B（OI-15/OI-21）: chat_trace に貯めた実トレースを使い、
回答プロンプトだけを差し替えて新旧を比較する。

**同じ質問・同じ検索結果（chat_trace.sources）**に対して、--old と --new の
2つのシステムプロンプトで回答を生成し、並べて表示する。検索は再実行しないので
（保存済みチャンクを使う）、プロンプトの効果だけを純粋に比較できる＝再embeddingコストもゼロ。

使い方（api コンテナ内で実行する想定。DB/LLMキーは環境から取る）:
    python scripts/ab_prompt_test.py --old /tmp/v3.txt --new /tmp/v4.txt [--limit 8]

プロンプトファイルは ANSWER_SYSTEM_PROMPT の本文（{guild_name}/{current_datetime}/{context}
プレースホルダ入り）をそのまま置いたテキスト。
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timedelta, timezone

import psycopg

from src.rag.llm import ChatLLM
from src.rag.prompts import build_context, build_unknown_memory_rule


def _now_str(tz_offset: int = 9) -> str:
    tz = timezone(timedelta(hours=tz_offset))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M JST")


def _fill(prompt: str, guild_name: str, context: str) -> str:
    return (
        prompt.replace("{guild_name}", guild_name)
        .replace("{current_datetime}", _now_str())
        .replace("{context}", context)
        .replace("{speaker_section}", "")
        .replace("{mimic_section}", "")
        .replace("{taught_memories}", "")
        .replace("{unknown_memory_rule}", build_unknown_memory_rule())
        .replace("{mimic_final_reminder}", "")
    )


def _fetch_traces(limit: int) -> list[dict]:
    dsn = os.environ.get("DATABASE_URL")
    rows: list[dict] = []
    with psycopg.connect(dsn) as conn:
        cur = conn.execute(
            "SELECT question, sources FROM chat_trace "
            "ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        for question, sources in cur.fetchall():
            rows.append({"question": question, "sources": sources or []})
    return rows


async def _run(old_prompt: str, new_prompt: str, limit: int) -> None:
    guild_name = os.environ.get("AB_GUILD_NAME", "わいわい")
    model = os.environ.get("AB_ANSWER_MODEL", "deepseek/deepseek-v3.2")
    llm = ChatLLM(
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    )
    traces = _fetch_traces(limit)
    print(f"model={model} / guild_name={guild_name} / traces={len(traces)}\n")
    for t in traces:
        context = build_context(t["sources"])
        sys_old = _fill(old_prompt, guild_name, context)
        sys_new = _fill(new_prompt, guild_name, context)
        old = await llm.complete(model, sys_old, t["question"], temperature=0.7, max_tokens=1500)
        new = await llm.complete(model, sys_new, t["question"], temperature=0.7, max_tokens=1500)
        print("=" * 72)
        print(f"Q: {t['question']}  （ヒット {len(t['sources'])} 件）")
        print("-" * 72)
        print(f"[OLD]\n{old.text.strip()}\n")
        print(f"[NEW]\n{new.text.strip()}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="回答プロンプトのA/B（chat_trace利用）")
    ap.add_argument("--old", required=True, help="旧プロンプト本文のテキストファイル")
    ap.add_argument("--new", required=True, help="新プロンプト本文のテキストファイル")
    ap.add_argument("--limit", type=int, default=8, help="比較する最新トレース件数")
    args = ap.parse_args()
    old_prompt = open(args.old, encoding="utf-8").read()
    new_prompt = open(args.new, encoding="utf-8").read()
    asyncio.run(_run(old_prompt, new_prompt, args.limit))


if __name__ == "__main__":
    main()
