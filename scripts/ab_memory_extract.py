#!/usr/bin/env python3
"""「覚えておいて」抽出（OI-24・書き込み）の A/B（使い捨て評価スクリプト）。

同一発話セットを2バリアントで比較する:
  - llm   : 本番の RagEngine.extract_memory（LLMで subject/content 構造化・記憶不要ならnull）
  - naive : 素朴保存（フレーズを除去して残り全文を content・subject なし・null判定なし＝常に保存）

発話は2種類（正解ラベル付き）:
  - SHOULD : 記憶すべき事実を含む。llm が subject/content を正しく取れるほど良い。
  - NOISE  : 「覚えておいて」を含むが記憶すべき事実は無い。保存しない(None)のが正解。
             naive は全部保存＝誤爆になる想定。
評価は LLM ジャッジ（gemini-2.5-flash）。SHOULD=抽出精度 / NOISE=誤爆を避けられたか。

実行（要: config.yml・APIキー。Qdrant/DBは不要＝extract はLLMのみ）:
    .venv/bin/python scripts/ab_memory_extract.py
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

JUDGE_MODEL = "google/gemini-2.5-flash"

# 素朴保存が剥がす依頼フレーズ（bot の _DEFAULT_REMEMBER_PHRASES 相当）。
REMEMBER_PHRASES = [
    "覚えておいてね", "覚えておいて", "覚えといてね", "覚えといて", "覚えてて",
    "おぼえておいて", "おぼえといて", "記憶しておいて", "記憶して", "メモして", "ね", "よ",
]

SHOULD = [
    {"text": "かにじるはケーキが好きだよ！覚えておいて！", "speaker": None,
     "expect": "subject=かにじる / content=ケーキが好き"},
    {"text": "わたしの誕生日3月25日だから覚えておいてね", "speaker": "まめぽん",
     "expect": "subject=まめぽん(話者本人) / content=誕生日は3月25日"},
    {"text": "毎週日曜の夜にゲーム会やってるの覚えといて", "speaker": None,
     "expect": "subject=null / content=毎週日曜の夜にゲーム会をやっている"},
    {"text": "れみちゃんはコーヒーより紅茶が好きって覚えておいて", "speaker": None,
     "expect": "subject=れみ / content=紅茶が好き(コーヒーより)"},
]
NOISE = [
    "この曲いいから覚えておいてね〜",
    "さっき誰かに『覚えておいて』って言われたわ",
    "『覚えておいて』って英語でなんて言うんだっけ？",
    "まあ細かいことは気にしないで、とりあえず覚えておいてくれればいいや",
]


def _build_engine():
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
    collected: list[dict] = []
    engine = RagEngine(
        cfg, store, embedder, llm,
        usage_recorder=lambda rows: collected.extend(rows),
    )
    return engine, llm, collected


def naive_extract(text: str) -> dict | None:
    """素朴保存: 依頼フレーズを除去して残り全文を content にする（null判定なし）。"""
    t = text
    for p in REMEMBER_PHRASES:
        t = t.replace(p, "")
    t = t.strip(" 　、。!！?？〜\n")
    return {"subject": None, "content": t} if t else None


def _fmt(res: dict | None) -> str:
    if not res:
        return "（保存しない）"
    return f"subject={res.get('subject')} / content={res.get('content')}"


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


async def judge_should(llm, text, expect, res):
    system = (
        "あなたは、ユーザー発話から覚えるべき事実を抽出するボットの出力を評価する審査員です。"
        "この発話には記憶すべき事実が含まれています。抽出結果が事実を正しく構造化できているかを"
        "1〜5で採点しJSONで返してください。\n"
        f"期待する抽出（正解の目安）: {expect}\n"
        "5=主語と内容を的確に抽出, 3=内容は取れたが主語が曖昧/冗長, 1=保存しなかった/的外れ\n"
        '出力: {"score":<1-5>,"reason":"<20字程度>"} のJSONのみ'
    )
    return await _judge(llm, system, f"【発話】{text}\n\n【抽出結果】{_fmt(res)}")


async def judge_noise(llm, text, res):
    system = (
        "あなたは、ユーザー発話から覚えるべき事実を抽出するボットの出力を評価する審査員です。"
        "この発話には『覚えておいて』等の語が含まれますが、**長期的に記憶すべき事実は含まれていません**。"
        "ボットが保存しない判断をできたかを1〜5で採点しJSONで返してください。\n"
        "5=保存しない(正解), 3=保存したが害の少ない内容, 1=無意味/誤った内容を誤って保存\n"
        '出力: {"score":<1-5>,"reason":"<20字程度>"} のJSONのみ'
    )
    return await _judge(llm, system, f"【発話】{text}\n\n【抽出結果】{_fmt(res)}")


async def main():
    engine, llm, _ = _build_engine()
    rows = []

    print("=== SHOULD（記憶すべき）===")
    for item in SHOULD:
        text, speaker, expect = item["text"], item["speaker"], item["expect"]
        print(f"[should] {text}")
        r_llm = await engine.extract_memory("ab-extract", text, speaker_name=speaker)
        r_naive = naive_extract(text)
        s_llm, why_llm = await judge_should(llm, text, expect, r_llm)
        s_naive, why_naive = await judge_should(llm, text, expect, r_naive)
        rows.append(dict(cat="should", text=text,
                         llm=dict(res=r_llm, score=s_llm, reason=why_llm),
                         naive=dict(res=r_naive, score=s_naive, reason=why_naive)))

    print("\n=== NOISE（記憶不要・誤爆チェック）===")
    for text in NOISE:
        print(f"[noise] {text}")
        r_llm = await engine.extract_memory("ab-extract", text)
        r_naive = naive_extract(text)
        s_llm, why_llm = await judge_noise(llm, text, r_llm)
        s_naive, why_naive = await judge_noise(llm, text, r_naive)
        rows.append(dict(cat="noise", text=text,
                         llm=dict(res=r_llm, score=s_llm, reason=why_llm),
                         naive=dict(res=r_naive, score=s_naive, reason=why_naive)))

    with open("scripts/ab_memory_extract_results.json", "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved scripts/ab_memory_extract_results.json")

    def agg(cat, key):
        sel = [r for r in rows if r["cat"] == cat]
        n = len(sel) or 1
        score = sum(r[key]["score"] for r in sel) / n
        saved = sum(1 for r in sel if r[key]["res"])  # 保存した件数
        return score, saved, n

    print("\n==== SUMMARY ====")
    for cat in ("should", "noise"):
        print(f"\n--- {cat} ---")
        for key in ("llm", "naive"):
            score, saved, n = agg(cat, key)
            print(f"{key:5s} score={score:.2f} saved={saved}/{n}")


if __name__ == "__main__":
    asyncio.run(main())
