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

    dense_lat: list[float] = []
    hybrid_lat: list[float] = []
    # カテゴリ別に [dense命中数, hybrid命中数, 採点対象数] を集計する。
    # category 未指定の項目は "（未分類）" にまとめる。
    cats: dict[str, list[int]] = {}

    for item in golden:
        q = item["question"]
        expect_any = item.get("expect_any", [])
        category = item.get("category", "（未分類）")
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
        print(f"[{category}] Q: {q}\n  書き換え: {rewritten}")
        if expect_any:
            dh, hh = _hit(d, expect_any), _hit(h, expect_any)
            agg = cats.setdefault(category, [0, 0, 0])
            agg[0] += int(dh)
            agg[1] += int(hh)
            agg[2] += 1
            mark = "  ← hybridで改善" if hh and not dh else (
                "  ← hybridで悪化" if dh and not hh else ""
            )
            print(f"  expect_any={expect_any}")
            print(f"  dense ヒット:{'○' if dh else '×'}  "
                  f"hybrid ヒット:{'○' if hh else '×'}{mark}")
        print(f"  dense  上位: {[c.get('channel_name') for c in d]}")
        print(f"  hybrid 上位: {[c.get('channel_name') for c in h]}")

    d_tot = sum(c[0] for c in cats.values())
    h_tot = sum(c[1] for c in cats.values())
    n_tot = sum(c[2] for c in cats.values())

    print("\n" + "=" * 70)
    print("【カテゴリ別ヒット率（recall@%d)】" % top_k)
    if n_tot:
        print(f"  {'カテゴリ':<16}{'dense':>10}{'hybrid':>10}{'n':>5}")
        for cat, (dn, hn, n) in cats.items():
            print(f"  {cat:<16}{dn / n:>9.0%}{hn / n:>10.0%}{n:>5}")
        print(f"  {'── 全体':<16}{d_tot / n_tot:>9.0%}{h_tot / n_tot:>10.0%}{n_tot:>5}")
    else:
        print("  （expect_any 付きの質問が無いためヒット率は未計測）")
    print(
        f"\n  latency p95: dense={_p95(dense_lat):.0f}ms  "
        f"hybrid={_p95(hybrid_lat):.0f}ms"
    )
    print(
        "\n判定の目安（#54 のゲート）:\n"
        "  - 固有名詞系で hybrid が dense を上回る（取りこぼし救済）\n"
        "  - 意味系で hybrid が dense を下回らない（RRFがdenseの強みを壊さない）\n"
        "  - latency が許容内\n"
        "  → 満たせば config.yml の rag.hybrid.enabled を true にする。"
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
