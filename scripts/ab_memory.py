#!/usr/bin/env python3
"""明示メモリ（OI-24）の効果A/B（使い捨て評価スクリプト）。

同一質問セットを2バリアントで比較する:
  - base : 現行（メモリ注入なし）
  - mem  : 「覚えておいて」で教わった事実（SAMPLE_MEMORIES）を回答プロンプトへ全件注入

本番の RagEngine をそのまま使う（mem は memory_provider 注入 ＋ rag.memory_enabled=true）。
質問は2種類:
  - 記憶系（MEMORY_QS）: 教わった事実に答えられるべき。mem が base を上回るほど良い。
  - 対照系（CONTROL_QS）: 過去ログ質問で教わった事実とは無関係。注入で脱線・劣化しないかの確認。
評価は LLM ジャッジ（gemini-2.5-flash）。記憶系/対照系で別軸採点。

実行（要: config.yml・実データguildの Qdrant・APIキー）:
    .venv/bin/python scripts/ab_memory.py
guild は環境変数 AB_GUILD_ID / AB_GUILD_NAME で上書きできる。
"""
from __future__ import annotations

import asyncio
import json
import os
import warnings

warnings.filterwarnings("ignore")
from dotenv import load_dotenv

load_dotenv()

from src.config import load_config
from src.embedder import Embedder
from src.rag.engine import RagEngine
from src.rag.llm import ChatLLM
from src.vectorstore import VectorStore

GUILD_ID = os.environ.get("AB_GUILD_ID", "1464840187061338317")  # 実データのある guild
GUILD_NAME = os.environ.get("AB_GUILD_NAME", "わいわい")

# れみに「覚えておいて」と教えた体の事実（本番では memories テーブルに入るデータ）。
SAMPLE_MEMORIES = [
    {"subject": "かにじる", "content": "ケーキが好き"},
    {"subject": "まめぽん", "content": "誕生日は3月25日"},
    {"subject": None, "content": "毎週日曜の夜にみんなでゲーム会をやっている"},
]

# 記憶系: 教わった事実に答えられるべき質問（expect = ジャッジに渡す正解の要点）。
MEMORY_QS = [
    {"q": "かにじるって何が好きだっけ？", "expect": "ケーキが好き"},
    {"q": "まめぽんの誕生日っていつ？", "expect": "3月25日（3/25）"},
    {"q": "ゲーム会っていつやってるんだっけ？", "expect": "毎週日曜の夜"},
]
# 対照系: 過去ログ質問（教わった事実とは無関係）。注入で脱線しない＝劣化しないかの確認用。
CONTROL_QS = [
    "moltbookって何だっけ？",
    "過去最悪のインシデントってどんな事件だったの？",
    "kimiちゃってどんな子？",
]

JUDGE_MODEL = "google/gemini-2.5-flash"


def _build(cfg, store, embedder, llm, with_memory: bool):
    """base / mem 用の engine を作る。mem は memory_provider＋memory_enabled。

    戻り値: (engine, collected) — collected は usage イベントの蓄積先（コスト集計用）。
    """
    c = json.loads(json.dumps(cfg))  # rag.memory_enabled だけ差し替えるためのコピー
    c.setdefault("rag", {})["memory_enabled"] = with_memory
    provider = (lambda gid: SAMPLE_MEMORIES) if with_memory else None
    collected: list[dict] = []
    engine = RagEngine(
        c, store, embedder, llm,
        usage_recorder=lambda rows: collected.extend(rows),
        memory_provider=provider,
    )
    return engine, collected


async def _ask(engine, collected, query, speaker_name=None):
    collected.clear()
    res = await engine.answer(
        GUILD_ID, query, guild_name=GUILD_NAME, speaker_name=speaker_name
    )
    cost = sum(float(e.get("cost_usd", 0.0)) for e in collected)
    return res["answer"], cost


def _parse_score(txt: str):
    txt = txt.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt[txt.find("{"):]
    try:
        d = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        return int(d.get("score", 0)), str(d.get("reason", ""))
    except Exception:
        return 0, f"parse_err:{txt[:30]}"


async def _judge(llm, system, user):
    comp = await llm.complete(JUDGE_MODEL, system, user, temperature=0.0, max_tokens=200)
    return _parse_score(comp.text)


async def judge_memory(llm, q, expect, answer):
    system = (
        "あなたはチャットボットの回答を評価する厳格な審査員です。"
        "このボットは『覚えておいて』と教わった事実を記憶として持っているべきです。"
        "次の質問に対し、教わった事実を正しく反映して答えられているかを1〜5で採点し、JSONで返してください。\n"
        f"教わった事実（正解の要点）: {expect}\n"
        "5=正解の事実をはっきり答えている, 3=曖昧/部分的, 1=答えられない・間違い・覚えてないと言う\n"
        '出力形式: {"score": <1-5>, "reason": "<20字程度の理由>"} のJSONのみ。'
    )
    return await _judge(llm, system, f"【質問】{q}\n\n【回答】{answer}")


async def judge_control(llm, q, answer):
    system = (
        "あなたはチャットボットの回答を評価する厳格な審査員です。"
        "このボットは過去ログを参照して質問に答えますが、別途いくつかの『教わった事実』"
        "（誰かの誕生日・好物・ゲーム会の曜日など）も記憶しています。"
        "次の回答が、その質問に関係のない『教わった事実』を不自然に持ち出して脱線していないか、"
        "質問にちゃんと向き合えているかを1〜5で採点し、JSONで返してください。\n"
        "5=脱線なく自然に答えている, 3=やや不自然, 1=無関係な記憶を持ち出して的外れ\n"
        '出力形式: {"score": <1-5>, "reason": "<20字程度の理由>"} のJSONのみ。'
    )
    return await _judge(llm, system, f"【質問】{q}\n\n【回答】{answer}")


async def main():
    cfg = load_config()
    qc = cfg.get("qdrant", {})
    emb_cfg = cfg.get("embedding", {})
    openai_cfg = cfg.get("openai", {})
    store = VectorStore(
        url=qc.get("url", "http://localhost:6333"),
        collection=qc.get("collection", "waiwai_chunks"),
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

    base_engine, base_c = _build(cfg, store, embedder, llm, with_memory=False)
    mem_engine, mem_c = _build(cfg, store, embedder, llm, with_memory=True)

    print(f"guild={GUILD_ID} ({GUILD_NAME}) / memories={len(SAMPLE_MEMORIES)}件\n")
    rows = []
    for item in MEMORY_QS:
        q, expect = item["q"], item["expect"]
        print(f"[memory] {q}")
        ba, bc = await _ask(base_engine, base_c, q)
        ma, mc = await _ask(mem_engine, mem_c, q)
        bs, br = await judge_memory(llm, q, expect, ba)
        ms, mr = await judge_memory(llm, q, expect, ma)
        rows.append(dict(
            cat="memory", q=q, expect=expect,
            base=dict(answer=ba, cost=bc, score=bs, reason=br),
            mem=dict(answer=ma, cost=mc, score=ms, reason=mr),
        ))
    for q in CONTROL_QS:
        print(f"[control] {q}")
        ba, bc = await _ask(base_engine, base_c, q)
        ma, mc = await _ask(mem_engine, mem_c, q)
        bs, br = await judge_control(llm, q, ba)
        ms, mr = await judge_control(llm, q, ma)
        rows.append(dict(
            cat="control", q=q,
            base=dict(answer=ba, cost=bc, score=bs, reason=br),
            mem=dict(answer=ma, cost=mc, score=ms, reason=mr),
        ))

    with open("scripts/ab_memory_results.json", "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("\nsaved scripts/ab_memory_results.json")

    def agg(cat, key):
        sel = [r for r in rows if r["cat"] == cat]
        n = len(sel) or 1
        return (
            sum(r[key]["score"] for r in sel) / n,
            sum(r[key]["cost"] for r in sel) / n,
        )

    print("\n==== SUMMARY ====")
    for cat in ("memory", "control"):
        print(f"\n--- {cat} ---")
        for key in ("base", "mem"):
            s, c = agg(cat, key)
            print(f"{key:4s} score={s:.2f} cost=${c*1000:.4f}/k")


if __name__ == "__main__":
    asyncio.run(main())
