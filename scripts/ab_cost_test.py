"""OI-16: 回答モデルのコスト/品質A/B計測（使い捨て・手動実行用）。

同じ質問・同じ検索結果（top_k）に対して複数の回答モデルで answer を生成し、
1問あたりの推定コスト（usage_log と同じ compute_cost）と回答テキストを並べて比較する。
検索（rewrite→embed→search）は1回だけ行い、両モデルへ完全に同条件の context を渡す。

実行（api イメージにマウントして使う）:
    docker compose run --rm -v "$PWD/scripts:/app/scripts" api python scripts/ab_cost_test.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from src.api import build_engine
from src.config import load_config
from src.rag.llm import Usage
from src.rag.prompts import (
    ANSWER_SYSTEM_PROMPT,
    build_context,
    build_unknown_memory_rule,
)
from src.usage import compute_cost

GUILD_ID = "1464840187061338317"
GUILD_NAME = "わいわい"
QUESTIONS = [
    "みんな最近どんな話してた？",
    "このサーバーで盛り上がった話題を教えて",
]
# 比較する回答モデル
MODELS = [
    "moonshotai/kimi-k2-0905",   # 現状
    "deepseek/deepseek-v3.2",    # 最新・最安級
]


async def run_one(engine, cfg, question: str) -> None:
    print("=" * 78)
    print(f"Q: {question}")

    # --- 検索は1回だけ（両モデル共通の context を作る） ---
    rewritten = await engine.rewrite(question)
    import asyncio as _aio
    vector, _ = await _aio.to_thread(
        engine.embedder.embed_one_with_usage, rewritten
    )
    hits = await _aio.to_thread(
        engine.store.search, GUILD_ID, vector, engine.top_k
    )
    print(f"rewritten: {rewritten}")
    print(f"hits: {len(hits)} 件 (top_k={engine.top_k})")

    system = ANSWER_SYSTEM_PROMPT.replace("{guild_name}", GUILD_NAME).replace(
        "{context}", build_context(hits)
    ).replace(
        "{unknown_memory_rule}", build_unknown_memory_rule()
    ).replace(
        "{mimic_final_reminder}", ""
    )
    pricing = cfg.get("pricing", {})

    for model in MODELS:
        comp = await engine.llm.complete(
            model, system, question,
            temperature=0.7, max_tokens=engine.answer_max_tokens,
        )
        u: Usage = comp.usage
        cost = compute_cost(pricing, model, u.prompt_tokens, u.completion_tokens)
        print("-" * 78)
        print(f"[{model}]")
        print(
            f"  tokens: prompt={u.prompt_tokens} completion={u.completion_tokens} "
            f"total={u.total_tokens}"
        )
        print(f"  cost : ${cost:.5f} / 問")
        print(f"  --- 回答 ---\n{comp.text}\n")


async def main() -> None:
    cfg = load_config()
    engine = build_engine(cfg)
    for q in QUESTIONS:
        await run_one(engine, cfg, q)


if __name__ == "__main__":
    asyncio.run(main())
