"""検索A/B（#55）: hybrid（案A・ベースライン）と hybrid+recency（案B）を比較する。

案A（ハイブリッド検索 #54）マージ後の**積み上げ評価**。recency 時間減衰を hybrid の
RRF 融合スコアの上に掛けたとき、

  (1) 時系列依存クエリ（「最近」「直近」など）で top_k の平均到達 age（日）が下がる
      ＝新しめの話が上位に来る、
  (2) 話題固定クエリでヒット率（recall@k）が落ちない、

を確認する。半減期は引数で振ってチューニングする（#55 は「半減期の最適値は実測で」）。

回答LLMは呼ばず**検索レーンだけ**を計測する（案B が変えるのは検索の並びなので）。
クエリ書き換えは本番同様 engine.rewrite を通す。recency は engine._apply_recency を直接使い、
本番（src/rag/engine.py）と同じ式で評価する。

使い方（メインの .env / config.yml を読む。稼働中 Qdrant に読み取りのみ）:
    # golden セットで定量評価（ヒット率・平均age・latency）
    python scripts/eval_recency.py <guild_id> eval/golden_recency.example.json
    # 半減期を変えて再採点（例: 7日）
    python scripts/eval_recency.py <guild_id> eval/golden_recency.example.json 7

golden.json の形式は eval/golden_recency.example.json 参照（category / question / expect_any）。
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
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


def _hit(hits: list[dict], expect_any: list[str]) -> bool:
    if not expect_any:
        return False
    blob = "\n".join(
        f"{h.get('context_text') or ''}\n{h.get('chunk_text') or ''}" for h in hits
    )
    return any(term in blob for term in expect_any)


def _mean_age_days(hits: list[dict], now: datetime) -> float | None:
    """top_k ヒットの anchor_timestamp の平均経過日数（新しいほど小さい）。"""
    ages = []
    for h in hits:
        ts = RagEngine._parse_anchor_ts(h.get("anchor_timestamp"))
        if ts is not None:
            ages.append((now - ts).total_seconds() / 86400.0)
    return statistics.mean(ages) if ages else None


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=20)[-1]


async def _run(guild_id: str, golden: list[dict], half_life: float | None) -> None:
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

    # recency を有効化した engine を組む（A/B の B レーンで _apply_recency を流用）。
    # 引数で半減期を上書きできるようにし、チューニングを回しやすくする。
    cfg.setdefault("rag", {}).setdefault("recency", {})
    cfg["rag"]["recency"]["enabled"] = True
    if half_life is not None:
        cfg["rag"]["recency"]["half_life_days"] = half_life
    engine = RagEngine(cfg, store, embedder, llm, sparse_encoder=sparse_encoder)
    top_k = engine.top_k
    prefetch_k = engine.hybrid_prefetch_k
    candidate_k = max(engine.recency_candidate_k, top_k)
    now = datetime.now(timezone.utc)

    print(f"guild_id={guild_id} / top_k={top_k} / candidate_k={candidate_k} / "
          f"prefetch_k={prefetch_k}")
    print(f"half_life_days={engine.recency_half_life_days} "
          f"recent_half_life_days={engine.recency_recent_half_life_days} "
          f"score_floor={engine.recency_score_floor}")
    print(f"Qdrant点数(このguild): {store.count(guild_id)}\n")

    base_lat: list[float] = []
    rec_lat: list[float] = []
    # カテゴリ別に [base命中, rec命中, n, base_age合計, rec_age合計, age対象数] を集計。
    cats: dict[str, list[float]] = {}

    for item in golden:
        q = item["question"]
        expect_any = item.get("expect_any", [])
        category = item.get("category", "（未分類）")
        rewritten = await engine.rewrite(q)
        vector = await asyncio.to_thread(embedder.embed_one, rewritten)
        sparse = sparse_encoder.encode(rewritten)
        recent = engine._is_recent_query(rewritten)

        # ハイブリッド候補プール（案A）を1回取得し、両レーンで共有する。
        t0 = time.perf_counter()
        candidate = await asyncio.to_thread(
            store.search, guild_id, vector, candidate_k, sparse, prefetch_k
        )
        search_ms = (time.perf_counter() - t0) * 1000
        base_lat.append(search_ms)

        baseline = candidate[:top_k]                       # 案A: 融合スコア順そのまま
        t0 = time.perf_counter()
        rec = engine._apply_recency(candidate, rewritten)   # 案B: 融合スコア×時間減衰
        rec_lat.append(search_ms + (time.perf_counter() - t0) * 1000)

        b_age = _mean_age_days(baseline, now)
        r_age = _mean_age_days(rec, now)
        agg = cats.setdefault(category, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        if expect_any:
            agg[0] += int(_hit(baseline, expect_any))
            agg[1] += int(_hit(rec, expect_any))
            agg[2] += 1
        if b_age is not None and r_age is not None:
            agg[3] += b_age
            agg[4] += r_age
            agg[5] += 1

        print("=" * 72)
        print(f"[{category}] Q: {q}\n  書き換え: {rewritten}"
              f"{'  ← 最近系と判定(半減期短縮)' if recent else ''}")
        if expect_any:
            bh, rh = _hit(baseline, expect_any), _hit(rec, expect_any)
            mark = "  ← recencyで改善" if rh and not bh else (
                "  ← recencyで悪化" if bh and not rh else ""
            )
            print(f"  expect_any={expect_any}")
            print(f"  baseline ヒット:{'○' if bh else '×'}  "
                  f"recency ヒット:{'○' if rh else '×'}{mark}")
        if b_age is not None:
            print(f"  平均age(日): baseline={b_age:.0f}  recency={r_age:.0f}")
        print(f"  baseline 上位: "
              f"{[(h.get('anchor_timestamp') or '')[:10] for h in baseline]}")
        print(f"  recency  上位: "
              f"{[(h.get('anchor_timestamp') or '')[:10] for h in rec]}")

    print("\n" + "=" * 72)
    print(f"【カテゴリ別ヒット率（recall@{top_k}）と平均age（日）】")
    print(f"  {'カテゴリ':<16}{'base率':>8}{'rec率':>8}{'n':>4}"
          f"{'base_age':>10}{'rec_age':>10}")
    b_hit = r_hit = n_hit = 0.0
    for cat, a in cats.items():
        n = a[2]
        nage = a[5]
        hit_b = f"{a[0]/n:>7.0%}" if n else f"{'-':>8}"
        hit_r = f"{a[1]/n:>7.0%}" if n else f"{'-':>8}"
        age_b = f"{a[3]/nage:>9.0f}" if nage else f"{'-':>10}"
        age_r = f"{a[4]/nage:>9.0f}" if nage else f"{'-':>10}"
        print(f"  {cat:<16}{hit_b}{hit_r}{int(n):>4}{age_b}{age_r}")
        b_hit += a[0]; r_hit += a[1]; n_hit += n
    if n_hit:
        print(f"  {'── 全体ヒット率':<16}{b_hit/n_hit:>7.0%}{r_hit/n_hit:>8.0%}"
              f"{int(n_hit):>4}")
    print(f"\n  latency p95: baseline(検索)={_p95(base_lat):.0f}ms  "
          f"recency(検索+減衰)={_p95(rec_lat):.0f}ms")
    print(
        "\n判定の目安（#55 のゲート）:\n"
        "  - 時系列(最近)系で recency の平均age が下がる（新しめの話が上位に来る）\n"
        "  - 話題(不変)系で recency のヒット率が baseline を下回らない\n"
        "  - latency 増が許容内（減衰はローカル計算なので軽微なはず）\n"
        "  → 満たせば config.yml の rag.recency.enabled を true にする。半減期は要チューニング。"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/eval_recency.py <guild_id> "
              "[golden.json] [half_life_days]")
        sys.exit(1)
    guild_id = sys.argv[1]
    golden_path = None
    half_life = None
    for arg in sys.argv[2:]:
        if arg.replace(".", "", 1).isdigit():
            half_life = float(arg)
        else:
            golden_path = arg
    if golden_path:
        golden = json.loads(Path(golden_path).read_text(encoding="utf-8"))
    else:
        golden = json.loads(
            (Path(__file__).resolve().parent.parent
             / "eval" / "golden_recency.example.json").read_text(encoding="utf-8")
        )
    asyncio.run(_run(guild_id, golden, half_life))


if __name__ == "__main__":
    main()
