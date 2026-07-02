"""リランクA/B（OI-9）: 同じ質問を「リランクOFF / ON」で投げ、検索ソースと回答を並べる。

使い方（メインの .env / config.yml を読む。実通信あり=OpenRouter/OpenAI/Jina）:
    python scripts/ab_rerank_test.py <guild_id> ["質問1" "質問2" ...]

稼働中の Qdrant(6333) に対して読み取りのみ。リランクの効果（dense上位 vs リランク後上位）を確認する。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

_MAIN = Path("/Users/aigamoid/Desktop/waiwai-oracle")
load_dotenv(_MAIN / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.embedder import Embedder            # noqa: E402
from src.rag.engine import RagEngine          # noqa: E402
from src.rag.llm import ChatLLM               # noqa: E402
from src.rag.reranker import Reranker         # noqa: E402
from src.vectorstore import VectorStore       # noqa: E402

_DEFAULT_QS = [
    "このサーバーで最近どんな話をしてた？",
    "かにじについての話は？",
    "AIエージェントやBotの話題を教えて",
]


def _chunk_key(s: dict) -> str:
    """チャンクを識別するキー（同一チャンネル内の並べ替えも見えるよう anchor を使う）。"""
    return f"{s.get('channel_name')}@{s.get('anchor_timestamp')}"


def _fmt_sources(sources: list[dict]) -> str:
    lines = []
    for i, s in enumerate(sources, 1):
        score = s.get("score")
        score_s = f"{score:.3f}" if isinstance(score, (int, float)) else "—"
        lines.append(f"    {i}. [{score_s}] #{s.get('channel_name')} @ {s.get('anchor_timestamp')}")
    return "\n".join(lines) or "    （なし）"


async def _run(guild_id: str, questions: list[str]) -> None:
    cfg = yaml.safe_load((_MAIN / "config.yml").read_text(encoding="utf-8"))
    rag = cfg.setdefault("rag", {})
    rag["reranker"] = {
        "enabled": True,
        "model": "jina-reranker-v2-base-multilingual",
        "top_n": 30,
    }
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
    reranker = Reranker(api_key=os.environ.get("JINA_API_KEY"))

    engine_off = RagEngine(cfg, store, embedder, llm, reranker=None)
    engine_on = RagEngine(cfg, store, embedder, llm, reranker=reranker)

    print(f"guild_id={guild_id} / top_k={engine_on.top_k} / top_n={engine_on.rerank_top_n}")
    print(f"Qdrant点数(このguild): {store.count(guild_id)}\n")

    for q in questions:
        print("=" * 70)
        print(f"Q: {q}")
        off = await engine_off.answer(guild_id, q)
        on = await engine_on.answer(guild_id, q)
        print(f"  書き換え: {off['rewritten_query']}")
        print("  [OFF] dense上位:")
        print(_fmt_sources(off["sources"]))
        print("  [ON ] リランク後:")
        print(_fmt_sources(on["sources"]))
        off_keys = [_chunk_key(s) for s in off["sources"]]
        on_keys = [_chunk_key(s) for s in on["sources"]]
        order_changed = off_keys != on_keys
        set_changed = set(off_keys) != set(on_keys)
        new_in = len(set(on_keys) - set(off_keys))
        print(
            f"  → 並びの変化: {'あり' if order_changed else 'なし'} / "
            f"集合の変化: {'あり' if set_changed else 'なし'}"
            f"（denseの上位5に無かったチャンクをリランクが採用: {new_in}件）"
        )
        print(f"  [OFF回答] {off['answer'][:160]}")
        print(f"  [ON 回答] {on['answer'][:160]}")
        print()


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/ab_rerank_test.py <guild_id> [質問...]")
        sys.exit(1)
    guild_id = sys.argv[1]
    questions = sys.argv[2:] or _DEFAULT_QS
    asyncio.run(_run(guild_id, questions))


if __name__ == "__main__":
    main()
