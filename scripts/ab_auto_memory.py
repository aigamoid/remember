#!/usr/bin/env python3
"""ab_auto_memory.py - 自動記憶（#56 案C）の A/B テスト harness（手動実行）。

「以前話した事実を覚えているか」を、自動記憶 ON / OFF で比較する。

- OFF（baseline）: 自動記憶なし。新規セッション（履歴空）で engine.answer に質問するだけ。
  以前の会話で語られた事実は覚えていない＝従来の「初対面っぽさ」。
- ON: フィクスチャの transcript から reconcile_memories で永続事実を抽出し、
  候補→承認（active 化）まで通してから、同じ質問を新規セッションで投げる。

指標: 事実再現率 / 誤事実(hallucination)率 / コスト(USD) / 人手1-5評価欄（手動記入用）。
判定は LLM-judge（rewriter_model・安価）で行う。結果は Markdown 表で標準出力に出す。

前提:
    docker compose up -d postgres qdrant
    .env に OPENROUTER_API_KEY / OPENAI_API_KEY、config.yml が存在すること。
実行:
    python scripts/ab_auto_memory.py
    python scripts/ab_auto_memory.py --guild-id ab_test_56 --fixture tests/fixtures/auto_memory_eval.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.config import load_config
from src.db import (
    approve_memory_candidate,
    get_connection,
    insert_memory_candidate,
)
from src.embedder import Embedder
from src.memory import MemoryProvider
from src.rag.engine import RagEngine
from src.rag.llm import ChatLLM
from src.vectorstore import VectorStore

JUDGE_PROMPT = """\
あなたは回答採点者です。質問と、Botの回答と、期待される事実を見て、JSONのみで採点します。

## 入力
質問: {question}
期待される事実: {expected}
Botの回答: {answer}

## 出力（JSONのみ）
{"recalled": <期待される事実を正しく答えられていれば true、できていなければ false。
   期待される事実が「情報なし」の場合は、知らない/わからない旨を答えていれば true>,
 "hallucinated": <会話に無い事実を、さも事実かのように具体的に断定していれば true。そうでなければ false>}
"""


class _CostBucket:
    """engine の usage_recorder として使い、cost_usd を現在のarmに加算する。"""

    def __init__(self) -> None:
        self.total = 0.0

    def reset(self) -> None:
        self.total = 0.0

    def __call__(self, rows: list[dict]) -> None:
        for r in rows:
            self.total += float(r.get("cost_usd") or 0.0)


def _build_engine(cfg: dict, cost: _CostBucket) -> RagEngine:
    """A/B 用 engine。明示メモリ注入を ON にし、usage はバケツに集約する。"""
    qdrant_cfg = cfg.get("qdrant", {})
    emb_cfg = cfg.get("embedding", {})
    openai_cfg = cfg.get("openai", {})
    cfg = {**cfg, "rag": {**cfg.get("rag", {}), "memory_enabled": True}}
    store = VectorStore(
        url=os.environ.get("QDRANT_URL")
        or qdrant_cfg.get("url", "http://localhost:6333"),
        collection=qdrant_cfg.get("collection", "waiwai_chunks"),
        vector_size=emb_cfg.get("dimensions", 1536),
    )
    embedder = Embedder(
        model=emb_cfg.get("model", "text-embedding-3-small"),
        dimensions=emb_cfg.get("dimensions", 1536),
    )
    llm = ChatLLM(
        api_key=openai_cfg.get("api_key") or os.environ.get("OPENROUTER_API_KEY"),
        base_url=openai_cfg.get("base_url", "https://openrouter.ai/api/v1"),
    )
    return RagEngine(
        cfg, store, embedder, llm,
        usage_recorder=cost, memory_provider=MemoryProvider(),
    )


def _transcript_text(fixture: dict) -> str:
    return "\n".join(
        f"{t['speaker']}: {t['text']}" for t in fixture["transcript"]
    )


def _clear_memories(conn, guild_id: str) -> None:
    """テスト guild の記憶を物理削除する（テスト専用 guild のみで使う）。"""
    conn.execute("DELETE FROM memories WHERE guild_id = %s", (guild_id,))
    conn.commit()


async def _judge(engine: RagEngine, question: str, expected: str, answer: str) -> dict:
    system = (
        JUDGE_PROMPT.replace("{question}", question)
        .replace("{expected}", expected)
        .replace("{answer}", answer)
    )
    comp = await engine.llm.complete(
        engine.rewriter_model, system, "採点して。", temperature=0.0, max_tokens=100,
    )
    data = engine._parse_memory_json(comp.text) or {}
    return {
        "recalled": bool(data.get("recalled")),
        "hallucinated": bool(data.get("hallucinated")),
    }


async def _run_arm(
    engine: RagEngine, cost: _CostBucket, conn, guild_id: str,
    guild_name: str, questions: list[dict], with_memory: bool,
) -> dict:
    cost.reset()
    rows = []
    for q in questions:
        result = await engine.answer(
            guild_id, q["q"], guild_name=guild_name, history=[],
        )
        answer = result["answer"]
        verdict = await _judge(engine, q["q"], q["expected_fact"], answer)
        rows.append({**q, "answer": answer, **verdict})
    recall_qs = [r for r in rows if r["type"] == "recall"]
    recalled = sum(1 for r in recall_qs if r["recalled"])
    halluc = sum(1 for r in rows if r["hallucinated"])
    return {
        "rows": rows,
        "recall_rate": recalled / len(recall_qs) if recall_qs else 0.0,
        "halluc_rate": halluc / len(rows) if rows else 0.0,
        "cost": cost.total,
        "with_memory": with_memory,
    }


async def main_async(args) -> None:
    load_dotenv()
    cfg = load_config()
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    guild_id = args.guild_id
    guild_name = fixture.get("guild_name", "テスト")
    questions = fixture["questions"]

    cost = _CostBucket()
    engine = _build_engine(cfg, cost)
    conn = get_connection()

    print(f"# 自動記憶 A/B テスト（#56 案C） guild={guild_id}\n")

    # --- OFF arm（baseline・記憶なし）---
    _clear_memories(conn, guild_id)
    off = await _run_arm(engine, cost, conn, guild_id, guild_name, questions, False)

    # --- ON arm（transcript から抽出→承認→active）---
    _clear_memories(conn, guild_id)
    conversation = _transcript_text(fixture)
    ops = await engine.reconcile_memories(guild_id, conversation, existing=[],
                                          guild_name=guild_name)
    applied = 0
    for op in ops:
        cid = insert_memory_candidate(
            conn, guild_id, op["op"], op.get("content"), op.get("subject"),
            op.get("target_id"), op.get("reason"), "ab_test",
        )
        if approve_memory_candidate(conn, cid):
            applied += 1
    on = await _run_arm(engine, cost, conn, guild_id, guild_name, questions, True)

    _clear_memories(conn, guild_id)
    conn.close()

    # --- レポート出力（Markdown）---
    print(f"抽出された記憶候補: {len(ops)} 件 / 承認(active)化: {applied} 件\n")
    print("## 抽出された記憶")
    for op in ops:
        print(f"- [{op['op']}] {op.get('subject') or '—'}: {op.get('content') or '—'}"
              f"  （根拠: {op.get('reason') or ''}）")
    print("\n## 指標サマリ\n")
    print("| 指標 | OFF（baseline） | ON（自動記憶） |")
    print("|---|---|---|")
    print(f"| 事実再現率 | {off['recall_rate']:.0%} | {on['recall_rate']:.0%} |")
    print(f"| 誤事実(hallucination)率 | {off['halluc_rate']:.0%} | {on['halluc_rate']:.0%} |")
    print(f"| コスト(USD) | ${off['cost']:.5f} | ${on['cost']:.5f} |")
    print(f"| 人手評価(1-5) | （手動記入） | （手動記入） |")

    for arm_name, arm in (("OFF（baseline）", off), ("ON（自動記憶）", on)):
        print(f"\n## 回答詳細 — {arm_name}\n")
        print("| 質問 | 種別 | 再現 | 誤事実 | 回答（要約） |")
        print("|---|---|---|---|---|")
        for r in arm["rows"]:
            ans = (r["answer"] or "").replace("\n", " ")
            ans = ans[:60] + ("…" if len(ans) > 60 else "")
            mark = "✅" if r["recalled"] else "❌"
            hal = "⚠️" if r["hallucinated"] else "—"
            print(f"| {r['q']} | {r['type']} | {mark} | {hal} | {ans} |")


def main() -> None:
    parser = argparse.ArgumentParser(description="自動記憶 A/B テスト（#56）")
    parser.add_argument("--guild-id", default="ab_test_56",
                        help="テスト専用 guild_id（実データと混ざらないよう既定はダミー）")
    parser.add_argument("--fixture",
                        default="tests/fixtures/auto_memory_eval.json")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
