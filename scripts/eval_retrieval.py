"""検索A/B（#54）: dense-only と hybrid を同じ質問で投げ、ヒット率/recall@k/latency を比較する。

#54 の「本番ON前提条件」である実データ評価のためのスクリプト。回答LLMは呼ばず、**検索レーンだけ**を
計測する（案A が変えるのは検索なので、評価もそこに絞ってコストを抑える）。クエリ書き換えは
本番同様 engine.rewrite を通す。

使い方（メインの .env / config.yml を読む。稼働中 Qdrant に読み取りのみ）:
    # golden セットで定量評価（ヒット率・recall@k・latency）
    python scripts/eval_retrieval.py <guild_id> path/to/golden.json
    # golden 無しなら既定質問でソースを並べて目視比較（latency のみ計測）
    python scripts/eval_retrieval.py <guild_id>

golden.json の形式（固有名詞・人名ヒットを問う質問を入れる）:
    [
      {"question": "かにじるって誰？", "expect_any": ["かにじる", "kanijiru"]},
      {"question": "先週のゲーム会の話", "expect_any": ["ゲーム会", "マイクラ"]}
    ]
expect_any のいずれかの文字列が、取得チャンク（chunk_text / context_text）に含まれれば「ヒット」。
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

_MAIN = Path("/Users/aigamoid/Desktop/waiwai-oracle")
load_dotenv(_MAIN / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.embedder import Embedder            # noqa: E402
from src.rag.engine import RagEngine          # noqa: E402
from src.rag.llm import ChatLLM               # noqa: E402
from src.sparse import SparseEncoder          # noqa: E402
from src.vectorstore import VectorStore       # noqa: E402

_DEFAULT_QS = [
    {"question": "このサーバーで最近どんな話をしてた？", "expect_any": []},
    {"question": "かにじるについての話は？", "expect_any": []},
    {"question": "AIエージェントやBotの話題を教えて", "expect_any": []},
]


def _hit(hits: list[dict], expect_any: list[str]) -> bool:
    """取得チャンクのどれかに expect_any のいずれかが含まれればヒット。"""
    if not expect_any:
        return False
    blob = "\n".join(
        f"{h.get('context_text') or ''}\n{h.get('chunk_text') or ''}" for h in hits
    )
    return any(term in blob for term in expect_any)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=20)[-1]  # 95パーセンタイル相当


async def _run(guild_id: str, golden: list[dict]) -> None:
    cfg = yaml.safe_load((_MAIN / "config.yml").read_text(encoding="utf-8"))
    emb_cfg = cfg.get("embedding", {})
    openai_cfg = cfg.get("openai", {})

    store = VectorStore(
        url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
        collection=cfg.get("qdrant", {}).get("collection", "waiwai_chunks"),
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
    sparse_encoder = SparseEncoder()
    # rewrite を本番同様に通すためだけに engine を使う（検索は store を直接叩く）。
    engine = RagEngine(cfg, store, embedder, llm)
    top_k = engine.top_k
    prefetch_k = engine.hybrid_prefetch_k

    print(f"guild_id={guild_id} / top_k={top_k} / prefetch_k={prefetch_k}")
    print(f"Qdrant点数(このguild): {store.count(guild_id)}\n")

    dense_hits = hybrid_hits = 0
    dense_lat: list[float] = []
    hybrid_lat: list[float] = []
    scored = 0  # expect_any のある（ヒット判定可能な）質問数

    for item in golden:
        q = item["question"]
        expect_any = item.get("expect_any", [])
        rewritten = await engine.rewrite(q)
        vector = await asyncio.to_thread(embedder.embed_one, rewritten)
        sparse = sparse_encoder.encode(rewritten)

        t0 = time.perf_counter()
        d = await asyncio.to_thread(store.search, guild_id, vector, top_k)
        dense_lat.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        h = await asyncio.to_thread(
            store.search, guild_id, vector, top_k, sparse, prefetch_k
        )
        hybrid_lat.append((time.perf_counter() - t0) * 1000)

        print("=" * 70)
        print(f"Q: {q}\n  書き換え: {rewritten}")
        if expect_any:
            scored += 1
            dh, hh = _hit(d, expect_any), _hit(h, expect_any)
            dense_hits += int(dh)
            hybrid_hits += int(hh)
            print(f"  expect_any={expect_any}")
            print(f"  dense  ヒット: {'○' if dh else '×'}")
            print(f"  hybrid ヒット: {'○' if hh else '×'}")
        print(f"  dense  上位: {[c.get('channel_name') for c in d]}")
        print(f"  hybrid 上位: {[c.get('channel_name') for c in h]}")

    print("\n" + "=" * 70)
    print("【集計】")
    if scored:
        print(
            f"  ヒット率(top_{top_k}): "
            f"dense={dense_hits}/{scored}={dense_hits / scored:.1%}  "
            f"hybrid={hybrid_hits}/{scored}={hybrid_hits / scored:.1%}"
        )
    else:
        print("  （expect_any 付きの質問が無いためヒット率は未計測）")
    print(
        f"  latency p95: dense={_p95(dense_lat):.0f}ms  "
        f"hybrid={_p95(hybrid_lat):.0f}ms"
    )
    print(
        "\n判定: hybrid のヒット率が dense を明確に上回り、latency が許容内なら "
        "config.yml の rag.hybrid.enabled を true にする（#54 のゲート）。"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/eval_retrieval.py <guild_id> [golden.json]")
        sys.exit(1)
    guild_id = sys.argv[1]
    if len(sys.argv) >= 3:
        golden = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    else:
        golden = _DEFAULT_QS
    asyncio.run(_run(guild_id, golden))


if __name__ == "__main__":
    main()
