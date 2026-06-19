#!/usr/bin/env python3
"""検索スキップ機能のA/Bテスト（使い捨て評価スクリプト）。

3バリアントを同一質問セットで比較する:
  - Baseline : 現行プロンプト + 常に検索
  - V1(prompt): 改善プロンプト（無関係な記憶なら素で雑談）+ 常に検索
  - V2(skip) : V1プロンプト + Rewriterが[NO_SEARCH]判定したら検索スキップ

評価はLLMジャッジ（gemini-2.5-flash）。雑談系/記憶系で別軸で1-5採点。
実行: .venv/bin/python scripts/ab_search_skip.py
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import warnings

warnings.filterwarnings("ignore")
from dotenv import load_dotenv

load_dotenv()

from src.config import load_config
from src.embedder import Embedder
from src.rag.engine import RagEngine
from src.rag.llm import ChatLLM, Usage
from src.rag.prompts import (
    ANSWER_SYSTEM_PROMPT,
    REWRITER_SYSTEM_PROMPT,
    build_context,
)
from src.usage import compute_cost
from src.vectorstore import VectorStore

GUILD_ID = "1464840187061338317"  # 実データのある guild（31チャンク）
GUILD_NAME = "わいわい"

# ---- バリアント別プロンプト --------------------------------------------------

# ① 改善: 「質問の種類を見て、過去ログと無関係なら記憶に絡めず素で応じる」を先頭に追加
ANSWER_V1 = ANSWER_SYSTEM_PROMPT.replace(
    "## 回答方針\n",
    "## 回答方針\n"
    "- **まず質問の種類を見る。** 挨拶・雑談・ゲーム（じゃんけん等）・一般常識・"
    "簡単な計算など、{guild_name}の過去ログと関係ない入力には、記憶に無理に絡めず、"
    "れみちゃんとして普通に楽しく応じる（「覚えてないかも」で断らない）。"
    "過去ログに関係する質問のときだけ、下記のように記憶を辿って具体的に答える。\n",
)

# ② Rewriterに検索要否判定を兼務させる（迷ったら検索に倒す）
REWRITER_V2 = REWRITER_SYSTEM_PROMPT.replace(
    "## ルール（上から順に適用）\n",
    "## ルール（上から順に適用）\n"
    "0. **検索要否判定（最優先）**: 入力が挨拶・雑談・ゲーム要求（じゃんけん等）・"
    "一般常識・天気・簡単な計算など、Discord過去ログを参照する必要が明らかに無い場合は、"
    "クエリの代わりに `[NO_SEARCH]` だけを出力する。少しでも過去の会話・人物・出来事に"
    "関わる可能性があるなら検索する（迷ったら必ず検索＝書き換えクエリを出す）。\n",
)
NO_SEARCH_TOKEN = "[NO_SEARCH]"

# ② スキップ時の回答プロンプト: 記憶セクションを雑談用センチネルに差し替え
SKIP_CONTEXT = "（このメッセージは雑談・一般的なやり取りなので、過去ログは参照していないよ）"


def _build_components():
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
    return cfg, store, embedder, llm


# ---- 質問セット --------------------------------------------------------------
CHITCHAT = [
    "じゃんけんしよう！",
    "今日の天気は？",
    "こんにちは！",
    "1たす1は？",
    "しりとりしよ、最初は『りんご』からね",
    "ありがとう、助かったよ！",
]
MEMORY = [
    "moltbookって何だっけ？",
    "過去最悪のインシデントってどんな事件だったの？",
    "社内QAポータルを作る話、どんな構成だった？",
    "kimiちゃってどんな子？",
    "Discordのフォーラム機能を使う話、あったよね？",
    "一番最初に話した内容って何だった？",
]


class Runner:
    def __init__(self, cfg, store, embedder, llm):
        self.cfg = cfg
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.rag = cfg.get("rag", {})
        self.rewriter_model = self.rag.get("rewriter_model", "google/gemini-2.5-flash")
        self.answer_model = self.rag.get("answer_model", "deepseek/deepseek-v3.2")
        self.top_k = self.rag.get("top_k", 5)
        self.pricing = cfg.get("pricing", {})
        self.now = time.strftime("%Y-%m-%d %H:%M JST")

    async def _rewrite(self, system, query):
        comp = await self.llm.complete(
            self.rewriter_model, system.replace("{current_datetime}", self.now),
            query, temperature=0.2, max_tokens=256,
        )
        return comp.text.strip(), comp.usage

    async def _search(self, rewritten):
        vec, emb_tok = await asyncio.to_thread(
            self.embedder.embed_one_with_usage, rewritten
        )
        hits = await asyncio.to_thread(self.store.search, GUILD_ID, vec, self.top_k)
        return hits, emb_tok

    async def _answer(self, system_tpl, context, query):
        system = (
            system_tpl.replace("{guild_name}", GUILD_NAME)
            .replace("{current_datetime}", self.now)
            .replace("{context}", context)
        )
        comp = await self.llm.complete(
            self.answer_model, system, query, temperature=0.7, max_tokens=1500,
        )
        return comp.text, comp.usage

    def _cost(self, model, u: Usage):
        return compute_cost(self.pricing, model, u.prompt_tokens, u.completion_tokens)

    async def run_baseline(self, query):
        t0 = time.perf_counter()
        rw, u_rw = await self._rewrite(REWRITER_SYSTEM_PROMPT, query)
        hits, emb = await self._search(rw)
        ans, u_a = await self._answer(ANSWER_SYSTEM_PROMPT, build_context(hits), query)
        cost = self._cost(self.rewriter_model, u_rw) + self._cost(self.answer_model, u_a)
        return dict(answer=ans, rewritten=rw, skipped=False, n_hits=len(hits),
                    latency_ms=int((time.perf_counter() - t0) * 1000), cost=cost)

    async def run_v1(self, query):
        t0 = time.perf_counter()
        rw, u_rw = await self._rewrite(REWRITER_SYSTEM_PROMPT, query)
        hits, emb = await self._search(rw)
        ans, u_a = await self._answer(ANSWER_V1, build_context(hits), query)
        cost = self._cost(self.rewriter_model, u_rw) + self._cost(self.answer_model, u_a)
        return dict(answer=ans, rewritten=rw, skipped=False, n_hits=len(hits),
                    latency_ms=int((time.perf_counter() - t0) * 1000), cost=cost)

    async def run_v2(self, query):
        t0 = time.perf_counter()
        rw, u_rw = await self._rewrite(REWRITER_V2, query)
        cost = self._cost(self.rewriter_model, u_rw)
        if NO_SEARCH_TOKEN in rw:
            ans, u_a = await self._answer(ANSWER_V1, SKIP_CONTEXT, query)
            cost += self._cost(self.answer_model, u_a)
            return dict(answer=ans, rewritten=rw, skipped=True, n_hits=0,
                        latency_ms=int((time.perf_counter() - t0) * 1000), cost=cost)
        hits, emb = await self._search(rw)
        ans, u_a = await self._answer(ANSWER_V1, build_context(hits), query)
        cost += self._cost(self.answer_model, u_a)
        return dict(answer=ans, rewritten=rw, skipped=False, n_hits=len(hits),
                    latency_ms=int((time.perf_counter() - t0) * 1000), cost=cost)


JUDGE_MODEL = "google/gemini-2.5-flash"


async def judge(llm, category, question, answer):
    if category == "chitchat":
        axis = (
            "適切さ・自然さ: 挨拶/雑談/ゲーム/一般常識/計算などの入力に、"
            "アシスタント『れみちゃん』として自然に乗れているか。"
            "『覚えてないかも』等で不当に断ったり、的外れな過去ログを持ち出したりせず、"
            "ちゃんと相手をしているほど高得点。5=完璧に自然, 1=的外れ/不適切な拒否"
        )
    else:
        axis = (
            "回答品質: 過去ログの記憶を踏まえ、質問に具体的に答えられているか。"
            "固有名詞やエピソードを挙げて中身のある回答ほど高得点。"
            "不当に『覚えてない』と断ると低得点。5=的確で具体的, 1=答えになっていない"
        )
    system = (
        "あなたはチャットボットの回答を評価する厳格な審査員です。"
        "次の評価軸で1〜5の整数スコアを付け、JSONで返してください。\n"
        f"評価軸: {axis}\n"
        '出力形式: {"score": <1-5>, "reason": "<20字程度の理由>"} のJSONのみ。'
    )
    user = f"【質問】{question}\n\n【回答】{answer}"
    comp = await llm.complete(JUDGE_MODEL, system, user, temperature=0.0, max_tokens=200)
    txt = comp.text.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt[txt.find("{"):]
    try:
        d = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        return int(d.get("score", 0)), str(d.get("reason", ""))
    except Exception as e:
        return 0, f"parse_err:{txt[:40]}"


async def main():
    cfg, store, embedder, llm = _build_components()
    r = Runner(cfg, store, embedder, llm)
    rows = []
    sets = [("chitchat", CHITCHAT), ("memory", MEMORY)]
    for category, qs in sets:
        for q in qs:
            print(f"[run] ({category}) {q}")
            b = await r.run_baseline(q)
            v1 = await r.run_v1(q)
            v2 = await r.run_v2(q)
            sb, rb = await judge(llm, category, q, b["answer"])
            s1, r1 = await judge(llm, category, q, v1["answer"])
            s2, r2 = await judge(llm, category, q, v2["answer"])
            rows.append(dict(
                category=category, q=q,
                base=dict(**b, score=sb, jreason=rb),
                v1=dict(**v1, score=s1, jreason=r1),
                v2=dict(**v2, score=s2, jreason=r2),
            ))
    with open("scripts/ab_results.json", "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("\nsaved scripts/ab_results.json")

    # サマリ
    def agg(key, cat):
        sel = [x for x in rows if x["category"] == cat]
        n = len(sel)
        return dict(
            score=sum(x[key]["score"] for x in sel) / n,
            latency=sum(x[key]["latency_ms"] for x in sel) / n,
            cost=sum(x[key]["cost"] for x in sel) / n,
            skipped=sum(1 for x in sel if x[key]["skipped"]),
            n=n,
        )

    print("\n==== SUMMARY ====")
    for cat in ("chitchat", "memory"):
        print(f"\n--- {cat} ---")
        for key in ("base", "v1", "v2"):
            a = agg(key, cat)
            print(f"{key:5s} score={a['score']:.2f} lat={a['latency']:.0f}ms "
                  f"cost=${a['cost']*1000:.4f}/k skip={a['skipped']}/{a['n']}")


if __name__ == "__main__":
    asyncio.run(main())
