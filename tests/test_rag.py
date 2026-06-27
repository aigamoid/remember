"""src/rag/ のテスト（フェイクLLM・フェイクembedder・インメモリQdrant）"""

from __future__ import annotations

import asyncio

import pytest
from qdrant_client import QdrantClient

from src.rag.engine import RagEngine
from src.rag.llm import ChatLLM, Completion, Usage, strip_think
from src.rag.prompts import (
    NO_SEARCH_SENTINEL,
    SKIP_CONTEXT,
    build_context,
    build_memories,
    build_mimic_declaration,
    build_mimic_section,
    persona_is_empty,
    sanitize_persona_card,
)
from src.rag.reranker import RerankResult
from src.sparse import SparseEncoder
from src.vectorstore import VectorStore


class FakeLLM:
    """API を呼ばず固定応答を返す。呼び出し内容を記録する。

    responses の各要素は str（usage 0）か Completion か Exception。
    """

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def complete(
        self, model, system, user, temperature=0.7, max_tokens=None, history=None
    ):
        self.calls.append(
            {
                "model": model, "system": system, "user": user,
                "temperature": temperature, "max_tokens": max_tokens,
                "history": history,
            }
        )
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if isinstance(resp, Completion):
            return resp
        return Completion(text=resp, model=model)


class FakeEmbedder:
    model = "text-embedding-3-small"

    def __init__(self, dimensions: int = 4, tokens: int = 7) -> None:
        self.dimensions = dimensions
        self.tokens = tokens
        self.embedded: list[str] = []

    def embed(self, texts):
        self.embedded.extend(texts)
        return [[1.0] + [0.0] * (self.dimensions - 1) for _ in texts]

    def embed_one(self, text):
        return self.embed([text])[0]

    def embed_one_with_usage(self, text):
        return self.embed_one(text), self.tokens


class FakeReranker:
    """API を呼ばず固定の並び替えを返す。order=None なら元の順序のまま。"""

    model = "fake-reranker"

    def __init__(self, order=None, tokens: int = 11, exc: Exception | None = None):
        self._order = order
        self._tokens = tokens
        self._exc = exc
        self.calls: list[dict] = []

    async def rerank(self, query, documents, top_k):
        self.calls.append(
            {"query": query, "documents": list(documents), "top_k": top_k}
        )
        if self._exc is not None:
            raise self._exc
        order = self._order if self._order is not None else list(range(len(documents)))
        return RerankResult(order=order[:top_k], total_tokens=self._tokens)


@pytest.fixture
def store():
    s = VectorStore(
        client=QdrantClient(":memory:"), collection="test", vector_size=4
    )
    s.ensure_collection()
    return s


def _seed(store, guild_id="g1", chunk_text="昨日の飲み会の話", context_text=None):
    store.upsert(
        [{
            "guild_id": guild_id,
            "chunk_id": "c1",
            "channel_id": "ch1",
            "channel_name": "general",
            "chunk_text": chunk_text,
            "context_text": context_text,
            "anchor_timestamp": "2024-01-01T00:00:00+00:00",
        }],
        [[1.0, 0.0, 0.0, 0.0]],
    )


CFG = {"guild_id": "g1", "rag": {"top_k": 5}}


def _engine(store, llm) -> RagEngine:
    return RagEngine(CFG, store, FakeEmbedder(), llm)


def _seed_many(store, vectors, guild_id="g1"):
    """vectors の数だけチャンクを登録する。channel_name は c0,c1,... で識別できる。"""
    payloads = [
        {
            "guild_id": guild_id,
            "chunk_id": f"c{i}",
            "channel_id": "ch1",
            "channel_name": f"c{i}",
            "chunk_text": f"本文{i}",
            "context_text": None,
            "anchor_timestamp": "2024-01-01T00:00:00+00:00",
        }
        for i in range(len(vectors))
    ]
    store.upsert(payloads, vectors)


def _engine_rr(store, llm, reranker, enabled=True, top_n=30, top_k=5) -> RagEngine:
    cfg = {"rag": {"top_k": top_k, "reranker": {"enabled": enabled, "top_n": top_n}}}
    return RagEngine(cfg, store, FakeEmbedder(), llm, reranker=reranker)


# ── strip_think ─────────────────────────────────────────────────────────────

class TestStripThink:
    def test_removes_think_tag(self):
        assert strip_think("<think>考え中</think>答え") == "答え"

    def test_no_tag_unchanged(self):
        assert strip_think("そのまま") == "そのまま"


# ── ChatLLM.complete のメッセージ組み立て ───────────────────────────────────

class _RecordingClient:
    """OpenAI互換クライアントの最小フェイク。create に渡された messages を記録する。"""

    def __init__(self) -> None:
        self.captured: dict = {}
        outer = self

        class _Completions:
            async def create(self, *, model, messages, temperature, max_tokens):
                outer.captured = {"model": model, "messages": messages}

                class _Msg:
                    content = "応答本文"

                class _Choice:
                    message = _Msg()

                class _Resp:
                    choices = [_Choice()]
                    usage = None

                return _Resp()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class TestChatLLMMessages:
    def test_without_history_system_then_user(self):
        client = _RecordingClient()
        llm = ChatLLM(client=client)
        asyncio.run(llm.complete("m", "システム", "ユーザー"))
        roles = [m["role"] for m in client.captured["messages"]]
        assert roles == ["system", "user"]

    def test_history_inserted_between_system_and_user(self):
        client = _RecordingClient()
        llm = ChatLLM(client=client)
        hist = [
            {"role": "user", "content": "前q"},
            {"role": "assistant", "content": "前a"},
        ]
        asyncio.run(llm.complete("m", "システム", "今のq", history=hist))
        msgs = client.captured["messages"]
        assert [m["role"] for m in msgs] == [
            "system", "user", "assistant", "user"
        ]
        assert msgs[1]["content"] == "前q"
        assert msgs[-1]["content"] == "今のq"


# ── build_context ───────────────────────────────────────────────────────────

class TestBuildContext:
    def test_empty_hits(self):
        assert "見つからなかった" in build_context([])

    def test_chunk_only(self):
        out = build_context([{"chunk_text": "本文A", "context_text": None}])
        assert out == "本文A"

    def test_with_context_text(self):
        out = build_context([{"chunk_text": "本文A", "context_text": "文脈A"}])
        assert "[CONTEXT]\n文脈A\n[CHUNK]\n本文A" == out

    def test_multiple_hits_separated(self):
        out = build_context(
            [
                {"chunk_text": "本文A", "context_text": None},
                {"chunk_text": "本文B", "context_text": None},
            ]
        )
        assert "\n\n---\n\n" in out


# ── RagEngine.rewrite ───────────────────────────────────────────────────────

class TestRewrite:
    def test_returns_llm_output(self, store):
        llm = FakeLLM(["書き換え済みクエリ"])
        out = asyncio.run(_engine(store, llm).rewrite("あれどうなった？"))
        assert out == "書き換え済みクエリ"

    def test_injects_current_datetime(self, store):
        llm = FakeLLM(["q"])
        asyncio.run(_engine(store, llm).rewrite("query"))
        assert "{current_datetime}" not in llm.calls[0]["system"]
        assert "現在の日時（JST）: 20" in llm.calls[0]["system"]

    def test_empty_response_falls_back(self, store):
        llm = FakeLLM(["  "])
        out = asyncio.run(_engine(store, llm).rewrite("元クエリ"))
        assert out == "元クエリ"

    def test_llm_error_falls_back(self, store):
        llm = FakeLLM([RuntimeError("API down")])
        out = asyncio.run(_engine(store, llm).rewrite("元クエリ"))
        assert out == "元クエリ"

    def test_uses_low_temperature(self, store):
        llm = FakeLLM(["q"])
        asyncio.run(_engine(store, llm).rewrite("query"))
        assert llm.calls[0]["temperature"] == 0.2

    def test_caps_rewriter_max_tokens(self, store):
        # 書き換えは短いので出力上限を絞る（残高不足で弾かれないように）
        llm = FakeLLM(["q"])
        asyncio.run(_engine(store, llm).rewrite("query"))
        assert llm.calls[0]["max_tokens"] == 256


# ── RagEngine.answer ────────────────────────────────────────────────────────

class TestAnswer:
    def test_full_flow(self, store):
        _seed(store)
        llm = FakeLLM(["書き換えクエリ", "れみちゃんの答えだよ〜"])
        result = asyncio.run(_engine(store, llm).answer("g1", "飲み会どうだった？"))
        assert result["answer"] == "れみちゃんの答えだよ〜"
        assert result["rewritten_query"] == "書き換えクエリ"
        assert result["sources"][0]["channel_name"] == "general"

    def test_context_injected_into_answer_prompt(self, store):
        _seed(store, chunk_text="渋谷で飲み会をした")
        llm = FakeLLM(["q", "答え"])
        asyncio.run(_engine(store, llm).answer("g1", "query"))
        answer_call = llm.calls[1]
        assert "渋谷で飲み会をした" in answer_call["system"]
        assert "{context}" not in answer_call["system"]
        assert "{guild_name}" not in answer_call["system"]

    def test_original_query_sent_to_answer_llm(self, store):
        _seed(store)
        llm = FakeLLM(["書き換えクエリ", "答え"])
        asyncio.run(_engine(store, llm).answer("g1", "元の質問"))
        assert llm.calls[1]["user"] == "元の質問"

    def test_rewritten_query_used_for_search(self, store):
        _seed(store)
        llm = FakeLLM(["書き換えクエリ", "答え"])
        embedder = FakeEmbedder()
        engine = RagEngine(CFG, store, embedder, llm)
        asyncio.run(engine.answer("g1", "元の質問"))
        assert embedder.embedded == ["書き換えクエリ"]

    def test_other_guild_data_not_visible(self, store):
        _seed(store, guild_id="other-guild", chunk_text="他サーバーの秘密")
        llm = FakeLLM(["q", "答え"])
        result = asyncio.run(_engine(store, llm).answer("g1", "query"))
        assert result["sources"] == []
        assert "他サーバーの秘密" not in llm.calls[1]["system"]

    def test_strips_think_from_answer(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答えのみ"])
        result = asyncio.run(_engine(store, llm).answer("g1", "query"))
        assert "<think>" not in result["answer"]

    def test_guild_name_injected_into_prompt(self, store):
        """リクエストで渡された guild_name がプロンプトに使われる。"""
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(
            _engine(store, llm).answer("g1", "query", guild_name="別のサーバー")
        )
        assert "別のサーバー" in llm.calls[1]["system"]

    def test_guild_name_falls_back_to_config(self, store):
        _seed(store)
        cfg = {"rag": {"top_k": 5, "guild_name": "コンフィグ名"}}
        llm = FakeLLM(["q", "答え"])
        engine = RagEngine(cfg, store, FakeEmbedder(), llm)
        asyncio.run(engine.answer("g1", "query"))
        assert "コンフィグ名" in llm.calls[1]["system"]

    def test_current_datetime_injected_into_answer_prompt(self, store):
        # OI-20: 回答プロンプトにも現在日時を入れる（過去ログの日付を「今日」と誤認しない）
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(_engine(store, llm).answer("g1", "query"))
        answer_system = llm.calls[1]["system"]
        assert "{current_datetime}" not in answer_system
        assert "今は 20" in answer_system  # _now_str() の "YYYY-..." が埋まっている

    def test_speaker_name_injected_into_answer_prompt(self, store):
        # OI-22: いま話しかけている人の表示名を回答プロンプトに差し込む
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(
            _engine(store, llm).answer("g1", "query", speaker_name="まめぽん")
        )
        answer_system = llm.calls[1]["system"]
        assert "{speaker_section}" not in answer_system
        assert "{speaker}" not in answer_system
        assert "まめぽん" in answer_system
        assert "いま話しかけてくれている人" in answer_system

    def test_speaker_section_removed_when_no_speaker(self, store):
        # speaker_name 未指定（CLI等）ならブロックごと消える（プレースホルダも残らない）
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(_engine(store, llm).answer("g1", "query"))
        answer_system = llm.calls[1]["system"]
        assert "{speaker_section}" not in answer_system
        assert "いま話しかけてくれている人" not in answer_system

    def test_blank_speaker_treated_as_absent(self, store):
        # 空白だけの speaker はブロックを出さない
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(_engine(store, llm).answer("g1", "query", speaker_name="   "))
        assert "いま話しかけてくれている人" not in llm.calls[1]["system"]


# ── 明示メモリ build_memories（OI-24） ───────────────────────────────────────

class TestBuildMemories:
    def test_empty_returns_empty_string(self):
        assert build_memories([]) == ""

    def test_content_only(self):
        out = build_memories([{"content": "ケーキが好き"}])
        assert out == "- ケーキが好き"

    def test_with_subject(self):
        out = build_memories([{"subject": "かにじる", "content": "ケーキが好き"}])
        assert out == "- 〔かにじる〕ケーキが好き"

    def test_skips_blank_content(self):
        out = build_memories(
            [{"content": "  "}, {"subject": "x", "content": "残る"}]
        )
        assert out == "- 〔x〕残る"

    def test_multiple_lines(self):
        out = build_memories(
            [{"content": "A"}, {"subject": "B", "content": "C"}]
        )
        assert out == "- A\n- 〔B〕C"


# ── 明示メモリの回答プロンプト注入（OI-24） ──────────────────────────────────

def _engine_mem(store, llm, provider, enabled=True) -> RagEngine:
    cfg = {"rag": {"top_k": 5, "memory_enabled": enabled}}
    return RagEngine(cfg, store, FakeEmbedder(), llm, memory_provider=provider)


class TestMemoryInjection:
    def test_memories_injected_when_enabled(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        provider = lambda gid: [{"subject": "かにじる", "content": "ケーキが好き"}]
        asyncio.run(_engine_mem(store, llm, provider).answer("g1", "query"))
        system = llm.calls[1]["system"]
        assert "{taught_memories}" not in system
        assert "{memories}" not in system
        assert "みんなから教わって覚えていること" in system
        assert "〔かにじる〕ケーキが好き" in system

    def test_provider_receives_guild_id(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        seen = []
        provider = lambda gid: seen.append(gid) or [{"content": "x"}]
        asyncio.run(_engine_mem(store, llm, provider).answer("g1", "query"))
        assert seen == ["g1"]

    def test_not_injected_when_disabled(self, store):
        # memory_enabled=false なら provider があっても注入しない（ブロックも消える）
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        provider = lambda gid: [{"content": "教わった事実"}]
        asyncio.run(
            _engine_mem(store, llm, provider, enabled=False).answer("g1", "query")
        )
        system = llm.calls[1]["system"]
        assert "{taught_memories}" not in system
        assert "みんなから教わって覚えていること" not in system

    def test_section_removed_when_no_memories(self, store):
        # enabled でも 0 件ならブロックごと消える（プレースホルダも残らない）
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(_engine_mem(store, llm, lambda gid: []).answer("g1", "query"))
        system = llm.calls[1]["system"]
        assert "{taught_memories}" not in system
        assert "みんなから教わって覚えていること" not in system

    def test_provider_failure_does_not_break_answer(self, store):
        # 取得失敗（例外）でもメモリ無しで回答を続行する
        _seed(store)
        llm = FakeLLM(["q", "答えだよ"])

        def boom(gid):
            raise RuntimeError("DB down")

        result = asyncio.run(
            _engine_mem(store, llm, boom).answer("g1", "query")
        )
        assert result["answer"] == "答えだよ"
        assert "みんなから教わって覚えていること" not in llm.calls[1]["system"]


# ── 「覚えておいて」抽出 extract_memory（OI-24・書き込み） ────────────────────

class TestExtractMemory:
    def test_extracts_subject_and_content(self, store):
        llm = FakeLLM(['{"subject":"かにじる","content":"ケーキが好き"}'])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        res = asyncio.run(eng.extract_memory("g1", "かにじるはケーキ好き、覚えて"))
        assert res == {"subject": "かにじる", "content": "ケーキが好き"}

    def test_null_content_returns_none(self, store):
        # 覚えるべき事実が無い発話は content=null → 保存しない（None）
        llm = FakeLLM(['{"subject":null,"content":null}'])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        assert asyncio.run(eng.extract_memory("g1", "この曲いいね覚えて")) is None

    def test_null_subject_kept(self, store):
        llm = FakeLLM(['{"subject":null,"content":"毎週日曜にゲーム会"}'])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        res = asyncio.run(eng.extract_memory("g1", "ゲーム会覚えて"))
        assert res == {"subject": None, "content": "毎週日曜にゲーム会"}

    def test_code_fence_stripped(self, store):
        llm = FakeLLM(['```json\n{"subject":"x","content":"y"}\n```'])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        assert asyncio.run(eng.extract_memory("g1", "xはy覚えて")) == {
            "subject": "x", "content": "y"
        }

    def test_broken_json_returns_none(self, store):
        llm = FakeLLM(["これはJSONじゃないよ"])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        assert asyncio.run(eng.extract_memory("g1", "なにか")) is None

    def test_llm_error_returns_none(self, store):
        llm = FakeLLM([RuntimeError("API down")])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        assert asyncio.run(eng.extract_memory("g1", "なにか")) is None

    def test_speaker_injected_into_prompt(self, store):
        llm = FakeLLM(['{"subject":"まめぽん","content":"誕生日は3月25日"}'])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        res = asyncio.run(
            eng.extract_memory("g1", "わたしの誕生日3/25覚えて", speaker_name="まめぽん")
        )
        assert res["subject"] == "まめぽん"
        system = llm.calls[0]["system"]
        assert "まめぽん" in system
        assert "{speaker_line}" not in system

    def test_no_speaker_removes_placeholder(self, store):
        llm = FakeLLM(['{"subject":null,"content":"x"}'])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        asyncio.run(eng.extract_memory("g1", "x覚えて"))
        assert "{speaker_line}" not in llm.calls[0]["system"]

    def test_uses_low_temperature(self, store):
        llm = FakeLLM(['{"subject":null,"content":"x"}'])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        asyncio.run(eng.extract_memory("g1", "x覚えて"))
        assert llm.calls[0]["temperature"] == 0.1


# ── マルチターン会話履歴（OI-10） ────────────────────────────────────────────

class TestConversationHistory:
    def test_history_passed_to_both_rewrite_and_answer(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        hist = [
            {"role": "user", "content": "前の質問"},
            {"role": "assistant", "content": "前の回答"},
        ]
        asyncio.run(_engine(store, llm).answer("g1", "それ詳しく", history=hist))
        assert llm.calls[0]["history"] == hist  # rewrite
        assert llm.calls[1]["history"] == hist  # answer

    def test_history_none_passes_empty_list(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(_engine(store, llm).answer("g1", "query"))
        assert llm.calls[0]["history"] == []
        assert llm.calls[1]["history"] == []

    def test_history_capped_to_max_turns(self, store):
        _seed(store)
        cfg = {"rag": {"top_k": 5, "history_max_turns": 2}}
        llm = FakeLLM(["q", "答え"])
        engine = RagEngine(cfg, store, FakeEmbedder(), llm)
        # 4ペア(8件)渡しても直近2ペア(4件)に丸められる
        hist = []
        for i in range(4):
            hist.append({"role": "user", "content": f"q{i}"})
            hist.append({"role": "assistant", "content": f"a{i}"})
        asyncio.run(engine.answer("g1", "query", history=hist))
        sent = llm.calls[1]["history"]
        assert len(sent) == 4
        assert sent[0]["content"] == "q2"

    def test_prep_history_drops_invalid_entries(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        hist = [
            {"role": "system", "content": "捨てられる"},   # role不正
            {"role": "user", "content": "   "},            # 空内容
            {"role": "assistant", "content": "残る"},
            {"foo": "bar"},                                # 不正な形
        ]
        asyncio.run(_engine(store, llm).answer("g1", "query", history=hist))
        sent = llm.calls[1]["history"]
        assert sent == [{"role": "assistant", "content": "残る"}]

    def test_history_max_turns_zero_disables(self, store):
        _seed(store)
        cfg = {"rag": {"top_k": 5, "history_max_turns": 0}}
        llm = FakeLLM(["q", "答え"])
        engine = RagEngine(cfg, store, FakeEmbedder(), llm)
        hist = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
        asyncio.run(engine.answer("g1", "query", history=hist))
        assert llm.calls[1]["history"] == []  # answer
        assert llm.calls[0]["history"] == []  # rewrite も無効

    def test_history_char_budget_drops_oldest(self, store):
        # 文字数バジェットを超えたら古いメッセージから落とし、最新を残す
        _seed(store)
        cfg = {"rag": {"top_k": 5, "history_max_turns": 10, "history_max_chars": 50}}
        llm = FakeLLM(["q", "答え"])
        engine = RagEngine(cfg, store, FakeEmbedder(), llm)
        hist = [
            {"role": "user", "content": "A" * 40},
            {"role": "assistant", "content": "B" * 40},
            {"role": "user", "content": "C" * 40},
            {"role": "assistant", "content": "D" * 40},  # 最新
        ]
        asyncio.run(engine.answer("g1", "query", history=hist))
        sent = llm.calls[1]["history"]  # answer
        assert sent == [{"role": "assistant", "content": "D" * 40}]

    def test_rewriter_history_is_narrower_than_answer(self, store):
        # rewriter には回答側より少ないペアだけ渡す（token 二重計上を抑える）
        _seed(store)
        cfg = {"rag": {
            "top_k": 5, "history_max_turns": 5, "history_max_chars": 10000,
            "rewriter_history_max_turns": 1, "rewriter_history_max_chars": 10000,
        }}
        llm = FakeLLM(["q", "答え"])
        engine = RagEngine(cfg, store, FakeEmbedder(), llm)
        hist = []
        for i in range(3):
            hist.append({"role": "user", "content": f"q{i}"})
            hist.append({"role": "assistant", "content": f"a{i}"})
        asyncio.run(engine.answer("g1", "query", history=hist))
        rw = llm.calls[0]["history"]   # rewrite
        ans = llm.calls[1]["history"]  # answer
        assert len(ans) == 6           # 3ペア全部
        assert len(rw) == 2            # 直近1ペアのみ
        assert rw[0]["content"] == "q2"


# ── usage 計測（usage_recorder） ─────────────────────────────────────────────

_PRICING = {
    "google/gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "moonshotai/kimi-k2-0905": {"input": 0.60, "output": 2.50},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}


class TestUsageRecording:
    def _engine_with_recorder(self, store, llm):
        captured: list[dict] = []
        cfg = {"rag": {"top_k": 5}, "pricing": _PRICING}
        engine = RagEngine(
            cfg, store, FakeEmbedder(), llm, usage_recorder=captured.extend
        )
        return engine, captured

    def test_records_rewrite_embedding_answer(self, store):
        _seed(store)
        llm = FakeLLM([
            Completion("q", "google/gemini-2.5-flash", Usage(100, 20, 120)),
            Completion("答え", "moonshotai/kimi-k2-0905", Usage(5000, 300, 5300)),
        ])
        engine, captured = self._engine_with_recorder(store, llm)
        asyncio.run(engine.answer("g1", "質問", user_id="u1"))
        assert [e["kind"] for e in captured] == ["rewrite", "embedding", "answer"]
        assert all(e["guild_id"] == "g1" for e in captured)
        assert all(e["user_id"] == "u1" for e in captured)

    def test_answer_cost_computed_from_pricing(self, store):
        _seed(store)
        llm = FakeLLM([
            Completion("q", "google/gemini-2.5-flash", Usage(0, 0, 0)),
            Completion("答え", "moonshotai/kimi-k2-0905", Usage(5000, 300, 5300)),
        ])
        engine, captured = self._engine_with_recorder(store, llm)
        asyncio.run(engine.answer("g1", "質問"))
        answer_ev = next(e for e in captured if e["kind"] == "answer")
        # (5000*0.60 + 300*2.50) / 1e6 = 0.00375
        assert abs(answer_ev["cost_usd"] - 0.00375) < 1e-9

    def test_rewrite_failure_skips_its_usage(self, store):
        _seed(store)
        llm = FakeLLM([
            RuntimeError("down"),
            Completion("答え", "moonshotai/kimi-k2-0905", Usage(10, 5, 15)),
        ])
        engine, captured = self._engine_with_recorder(store, llm)
        asyncio.run(engine.answer("g1", "質問"))
        assert [e["kind"] for e in captured] == ["embedding", "answer"]

    def test_no_recorder_does_not_break(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        result = asyncio.run(_engine(store, llm).answer("g1", "質問"))
        assert result["answer"] == "答え"


# ── RagEngine リランク（OI-9）────────────────────────────────────────────────

# query=[1,0,0,0] に対する cosine が c0>c1>c2 になるベクトル（dense順を固定）
_RR_VECS = [[1.0, 0.0, 0, 0], [0.8, 0.6, 0, 0], [0.6, 0.8, 0, 0]]


class TestRerank:
    def test_reorders_hits(self, store):
        _seed_many(store, _RR_VECS)  # dense順: c0, c1, c2
        reranker = FakeReranker(order=[2, 0, 1])
        llm = FakeLLM(["書き換えq", "答え"])
        result = asyncio.run(_engine_rr(store, llm, reranker).answer("g1", "質問"))
        # リランク後の順序がそのまま sources に反映される
        assert [s["channel_name"] for s in result["sources"]] == ["c2", "c0", "c1"]
        # リランカーには書き換え後クエリが渡る
        assert reranker.calls[0]["query"] == "書き換えq"

    def test_retrieves_many_then_trims_to_top_k(self, store):
        _seed_many(store, _RR_VECS)  # 3件
        reranker = FakeReranker()  # 恒等並び
        llm = FakeLLM(["q", "答え"])
        result = asyncio.run(
            _engine_rr(store, llm, reranker, top_n=30, top_k=2).answer("g1", "質問")
        )
        # dense は候補を多め(3件すべて)取得 → リランカーに3件渡る
        assert len(reranker.calls[0]["documents"]) == 3
        # 最終的に top_k=2 件に絞られる
        assert len(result["sources"]) == 2

    def test_disabled_does_not_call_reranker(self, store):
        _seed_many(store, _RR_VECS)
        reranker = FakeReranker(order=[2, 1, 0])
        llm = FakeLLM(["q", "答え"])
        result = asyncio.run(
            _engine_rr(store, llm, reranker, enabled=False).answer("g1", "質問")
        )
        assert reranker.calls == []  # 無効時は呼ばれない
        assert result["answer"] == "答え"

    def test_failure_falls_back_to_dense(self, store):
        _seed_many(store, _RR_VECS)
        reranker = FakeReranker(exc=RuntimeError("rerank API down"))
        llm = FakeLLM(["q", "答え"])
        result = asyncio.run(
            _engine_rr(store, llm, reranker, top_k=2).answer("g1", "質問")
        )
        # 失敗してもクラッシュせず、dense順 top_k で回答する
        assert result["answer"] == "答え"
        assert [s["channel_name"] for s in result["sources"]] == ["c0", "c1"]

    def test_records_rerank_usage(self, store):
        _seed_many(store, _RR_VECS)
        captured: list[dict] = []
        reranker = FakeReranker(order=[0, 1, 2], tokens=11)
        llm = FakeLLM(["q", "答え"])
        cfg = {"rag": {"top_k": 5, "reranker": {"enabled": True, "top_n": 30}}}
        engine = RagEngine(
            cfg, store, FakeEmbedder(), llm,
            usage_recorder=lambda rows: captured.extend(rows), reranker=reranker,
        )
        asyncio.run(engine.answer("g1", "質問"))
        rerank_ev = next(e for e in captured if e["kind"] == "rerank")
        assert rerank_ev["total_tokens"] == 11
        assert rerank_ev["model"] == "fake-reranker"


# ── デバッグトレース（OI-21）────────────────────────────────────────────────
def _engine_trace(store, llm, recorder, enabled=True):
    """debug_trace を切り替えた engine を作る。recorder は dict を1件受ける callable。"""
    cfg = {"rag": {"top_k": 5, "debug_trace": enabled}}
    return RagEngine(cfg, store, FakeEmbedder(), llm, trace_recorder=recorder)


class TestDebugTrace:
    def test_records_when_enabled(self, store):
        _seed(store, chunk_text="渋谷で飲み会をした", context_text="文脈")
        captured: list[dict] = []
        llm = FakeLLM(["書き換えクエリ", "れみの答え"])
        engine = _engine_trace(store, llm, captured.append, enabled=True)
        asyncio.run(engine.answer("g1", "飲み会どうだった？", user_id="u1"))
        assert len(captured) == 1
        row = captured[0]
        assert row["guild_id"] == "g1"
        assert row["user_id"] == "u1"
        assert row["question"] == "飲み会どうだった？"
        assert row["rewritten_query"] == "書き換えクエリ"
        assert row["answer"] == "れみの答え"
        assert row["rerank_enabled"] is False
        # ヒットチャンクは本文・文脈・スコアまで残す（デバッグ用）
        assert row["sources"][0]["chunk_text"] == "渋谷で飲み会をした"
        assert row["sources"][0]["context_text"] == "文脈"
        assert "score" in row["sources"][0]
        # トークン/コスト/レイテンシが入る
        assert row["total_tokens"] > 0
        assert row["latency_ms"] >= 0

    def test_not_recorded_when_disabled(self, store):
        _seed(store)
        captured: list[dict] = []
        llm = FakeLLM(["q", "答え"])
        engine = _engine_trace(store, llm, captured.append, enabled=False)
        result = asyncio.run(engine.answer("g1", "質問"))
        assert captured == []
        assert result["answer"] == "答え"

    def test_not_recorded_without_recorder(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        # enabled でも recorder 未注入なら何も起きない（クラッシュしない）
        cfg = {"rag": {"top_k": 5, "debug_trace": True}}
        engine = RagEngine(cfg, store, FakeEmbedder(), llm, trace_recorder=None)
        result = asyncio.run(engine.answer("g1", "質問"))
        assert result["answer"] == "答え"

    def test_recorder_failure_does_not_break_answer(self, store):
        _seed(store)

        def boom(_row):
            raise RuntimeError("DB down")

        llm = FakeLLM(["q", "答え"])
        engine = _engine_trace(store, llm, boom, enabled=True)
        result = asyncio.run(engine.answer("g1", "質問"))
        # トレース記録が失敗しても回答は返る
        assert result["answer"] == "答え"

    def test_rerank_flag_true_when_reranking(self, store):
        _seed_many(store, _RR_VECS)
        captured: list[dict] = []
        reranker = FakeReranker(order=[2, 0, 1], tokens=5)
        llm = FakeLLM(["q", "答え"])
        cfg = {
            "rag": {
                "top_k": 2,
                "debug_trace": True,
                "reranker": {"enabled": True, "top_n": 30},
            }
        }
        engine = RagEngine(
            cfg, store, FakeEmbedder(), llm,
            reranker=reranker, trace_recorder=captured.append,
        )
        asyncio.run(engine.answer("g1", "質問"))
        assert captured[0]["rerank_enabled"] is True


# ── 検索ゲート（OI-23：必要なければベクトル検索をスキップ）─────────────────────

class TestSearchGate:
    def test_skips_search_when_rewriter_returns_sentinel(self, store):
        # Rewriter が [NO_SEARCH] を返したら埋め込み・検索を行わない
        _seed(store, chunk_text="関係ない過去ログ")
        embedder = FakeEmbedder()
        llm = FakeLLM([NO_SEARCH_SENTINEL, "じゃんけんしよ〜！れみはグー！"])
        engine = RagEngine(CFG, store, embedder, llm)
        result = asyncio.run(engine.answer("g1", "じゃんけんしよう！"))
        assert result["search_skipped"] is True
        assert result["sources"] == []
        assert embedder.embedded == []  # 埋め込みも検索も走っていない
        assert result["answer"] == "じゃんけんしよ〜！れみはグー！"

    def test_skip_uses_skip_context_not_empty_memory(self, store):
        # スキップ時は「見つからなかった」ではなく雑談用センチネルを差し込む
        _seed(store)
        llm = FakeLLM([NO_SEARCH_SENTINEL, "答え"])
        engine = RagEngine(CFG, store, FakeEmbedder(), llm)
        asyncio.run(engine.answer("g1", "こんにちは！"))
        answer_system = llm.calls[1]["system"]
        assert SKIP_CONTEXT in answer_system
        assert "見つからなかった" not in answer_system

    def test_skip_records_no_embedding_usage(self, store):
        # スキップ時の usage は rewrite と answer のみ（embedding は無い）
        _seed(store)
        captured: list[dict] = []
        cfg = {"rag": {"top_k": 5}, "pricing": _PRICING}
        llm = FakeLLM([NO_SEARCH_SENTINEL, "答え"])
        engine = RagEngine(
            cfg, store, FakeEmbedder(), llm, usage_recorder=captured.extend
        )
        asyncio.run(engine.answer("g1", "ありがとう！"))
        assert [e["kind"] for e in captured] == ["rewrite", "answer"]

    def test_normal_query_still_searches(self, store):
        # [NO_SEARCH] を含まない通常クエリは従来どおり検索する
        _seed(store, chunk_text="渋谷で飲み会をした")
        embedder = FakeEmbedder()
        llm = FakeLLM(["渋谷 飲み会", "答え"])
        engine = RagEngine(CFG, store, embedder, llm)
        result = asyncio.run(engine.answer("g1", "飲み会どうだった？"))
        assert result["search_skipped"] is False
        assert embedder.embedded == ["渋谷 飲み会"]
        assert result["sources"][0]["channel_name"] == "general"

    def test_gate_disabled_treats_sentinel_as_query(self, store):
        # search_gate=false なら [NO_SEARCH] を普通のクエリ扱いで検索する（無効化できる）
        _seed(store)
        embedder = FakeEmbedder()
        cfg = {"rag": {"top_k": 5, "search_gate": False}}
        llm = FakeLLM([NO_SEARCH_SENTINEL, "答え"])
        engine = RagEngine(cfg, store, embedder, llm)
        result = asyncio.run(engine.answer("g1", "じゃんけんしよう！"))
        assert result["search_skipped"] is False
        assert embedder.embedded == [NO_SEARCH_SENTINEL]

    def test_skip_disables_reranker(self, store):
        # スキップ時はリランカーも呼ばれない
        _seed_many(store, _RR_VECS)
        reranker = FakeReranker(order=[2, 0, 1])
        llm = FakeLLM([NO_SEARCH_SENTINEL, "答え"])
        result = asyncio.run(
            _engine_rr(store, llm, reranker).answer("g1", "じゃんけんしよう！")
        )
        assert result["search_skipped"] is True
        assert reranker.calls == []


# ── ハイブリッド検索（#54：dense + BM25 sparse / RRF）─────────────────────────

def _ws_sparse() -> SparseEncoder:
    return SparseEncoder(splitter=lambda t: t.split())


def _engine_hybrid(store, llm, enabled=True, encoder=None) -> RagEngine:
    cfg = {"rag": {"top_k": 5, "hybrid": {"enabled": enabled, "prefetch_k": 10}}}
    return RagEngine(
        cfg, store, FakeEmbedder(), llm,
        sparse_encoder=encoder if encoder is not None else _ws_sparse(),
    )


def _seed_with_sparse(store, channel, sparse, guild_id="g1", chunk_id=None):
    """dense は共線（[1,0,0,0]）にして sparse 一致だけで順位が決まるよう種をまく。"""
    store.upsert(
        [{
            "guild_id": guild_id,
            "chunk_id": chunk_id or channel,
            "channel_id": "ch1",
            "channel_name": channel,
            "chunk_text": f"本文{channel}",
            "context_text": None,
            "anchor_timestamp": "2024-01-01T00:00:00+00:00",
        }],
        [[1.0, 0.0, 0.0, 0.0]],
        [sparse],
    )


class TestHybrid:
    def test_keyword_match_ranked_first(self, store):
        enc = _ws_sparse()
        _seed_with_sparse(store, "A", enc.encode("かにじる"))
        _seed_with_sparse(store, "B", enc.encode("別の話題"))
        # 書き換え後クエリ "かにじる" の sparse が A の語にヒット → A が上位
        llm = FakeLLM(["かにじる", "答え"])
        result = asyncio.run(_engine_hybrid(store, llm, encoder=enc).answer("g1", "q"))
        assert result["sources"][0]["channel_name"] == "A"

    def test_disabled_uses_dense_only(self, store):
        # hybrid 無効なら sparse があっても dense-only 経路（クラッシュせず回答）
        enc = _ws_sparse()
        _seed_with_sparse(store, "A", enc.encode("かにじる"))
        llm = FakeLLM(["かにじる", "答え"])
        result = asyncio.run(
            _engine_hybrid(store, llm, enabled=False, encoder=enc).answer("g1", "q")
        )
        assert result["answer"] == "答え"

    def test_no_encoder_uses_dense_only(self, store):
        # encoder 未注入なら enabled でも dense-only（二重ガード）
        _seed(store)
        cfg = {"rag": {"top_k": 5, "hybrid": {"enabled": True}}}
        llm = FakeLLM(["q", "答え"])
        engine = RagEngine(cfg, store, FakeEmbedder(), llm, sparse_encoder=None)
        result = asyncio.run(engine.answer("g1", "q"))
        assert result["answer"] == "答え"

    def test_hybrid_respects_guild_filter(self, store):
        enc = _ws_sparse()
        _seed_with_sparse(store, "A", enc.encode("かにじる"), guild_id="g1")
        _seed_with_sparse(store, "B", enc.encode("かにじる"), guild_id="g2")
        llm = FakeLLM(["かにじる", "答え"])
        result = asyncio.run(_engine_hybrid(store, llm, encoder=enc).answer("g1", "q"))
        assert all(s["channel_name"] == "A" for s in result["sources"])


def _engine_mimic(store, llm, provider, enabled=True) -> RagEngine:
    cfg = {"rag": {"top_k": 5, "mimic_enabled": enabled}}
    return RagEngine(cfg, store, FakeEmbedder(), llm, mimic_provider=provider)


_CARD = {
    "nicknames": ["うさ"], "personality": "明るい", "likes": ["ゲーム"],
    "speech_style": "語尾に〜っす", "catchphrases": ["っす"], "confidence": "high",
}


class TestMimicInjection:
    """#49: 回答時に {mimic_section} が注入される/消える。"""

    def test_injected_when_enabled(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        provider = lambda gid, cid: {"display_name": "うさぎ", "card": _CARD}
        asyncio.run(
            _engine_mimic(store, llm, provider).answer("g1", "q", channel_id="c1")
        )
        system = llm.calls[1]["system"]
        assert "{mimic_section}" not in system
        assert "うさぎ" in system and "モノマネ" in system

    def test_provider_receives_guild_and_channel(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        seen = []
        provider = lambda gid, cid: seen.append((gid, cid)) or {
            "display_name": "X", "card": _CARD
        }
        asyncio.run(
            _engine_mimic(store, llm, provider).answer("g1", "q", channel_id="c9")
        )
        assert seen == [("g1", "c9")]

    def test_not_injected_when_disabled(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        provider = lambda gid, cid: {"display_name": "うさぎ", "card": _CARD}
        asyncio.run(
            _engine_mimic(store, llm, provider, enabled=False).answer(
                "g1", "q", channel_id="c1"
            )
        )
        system = llm.calls[1]["system"]
        assert "{mimic_section}" not in system
        assert "モノマネ" not in system

    def test_section_removed_without_channel_id(self, store):
        # channel_id 未指定（CLI等）なら mimic は効かずブロックも消える
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        provider = lambda gid, cid: {"display_name": "うさぎ", "card": _CARD}
        asyncio.run(_engine_mimic(store, llm, provider).answer("g1", "q"))
        system = llm.calls[1]["system"]
        assert "{mimic_section}" not in system
        assert "モノマネ" not in system

    def test_section_removed_when_none(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答え"])
        asyncio.run(
            _engine_mimic(store, llm, lambda gid, cid: None).answer(
                "g1", "q", channel_id="c1"
            )
        )
        assert "{mimic_section}" not in llm.calls[1]["system"]
        assert "モノマネ" not in llm.calls[1]["system"]

    def test_provider_failure_does_not_break_answer(self, store):
        _seed(store)
        llm = FakeLLM(["q", "答えだよ"])

        def boom(gid, cid):
            raise RuntimeError("DB down")

        result = asyncio.run(
            _engine_mimic(store, llm, boom).answer("g1", "q", channel_id="c1")
        )
        assert result["answer"] == "答えだよ"
        assert "モノマネ" not in llm.calls[1]["system"]


class TestBuildPersonaCard:
    """#49: build_persona_card のJSONパース・センシティブ除去・空判定。"""

    def test_parses_and_returns_card(self, store):
        import json
        llm = FakeLLM([json.dumps(_CARD)])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        card = asyncio.run(
            eng.build_persona_card("g1", "うさぎ", [{"content": "やっほ〜っす"}])
        )
        assert card and card["personality"] == "明るい"
        assert card["speech_style"] == "語尾に〜っす"

    def test_no_samples_returns_none(self, store):
        llm = FakeLLM([])  # 呼ばれない
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        assert asyncio.run(eng.build_persona_card("g1", "X", [])) is None

    def test_broken_json_returns_none(self, store):
        llm = FakeLLM(["これはJSONじゃない"])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        card = asyncio.run(
            eng.build_persona_card("g1", "X", [{"content": "発言"}])
        )
        assert card is None

    def test_sensitive_only_card_returns_none(self, store):
        import json
        bad = {
            "nicknames": [], "personality": "支持政党は自民", "likes": ["政治"],
            "speech_style": "宗教の話ばかり", "catchphrases": [], "confidence": "low",
        }
        llm = FakeLLM([json.dumps(bad)])
        eng = RagEngine(CFG, store, FakeEmbedder(), llm)
        card = asyncio.run(
            eng.build_persona_card("g1", "X", [{"content": "発言"}])
        )
        assert card is None  # センシティブ除去後に実質空


class TestMimicBuilders:
    """#49: prompts の builder/sanitizer の純粋関数テスト。"""

    def test_sanitize_removes_sensitive(self):
        out = sanitize_persona_card({
            "personality": "明るい", "speech_style": "宗教の話が多い",
            "likes": ["ゲーム", "政治"], "nicknames": ["うさ"],
            "catchphrases": [], "confidence": "high",
        })
        assert out["personality"] == "明るい"
        assert out["speech_style"] == ""        # センシティブ語で除去
        assert out["likes"] == ["ゲーム"]        # 「政治」だけ落ちる
        assert out["nicknames"] == ["うさ"]

    def test_persona_is_empty(self):
        assert persona_is_empty({"personality": "", "likes": [], "nicknames": [],
                                 "speech_style": "", "catchphrases": []})
        assert not persona_is_empty(_CARD)

    def test_build_section_empty_for_empty_card(self):
        assert build_mimic_section({}, "X") == ""

    def test_build_section_contains_traits(self):
        sec = build_mimic_section(_CARD, "うさぎ")
        assert "うさぎ" in sec and "明るい" in sec and "〜っす" in sec

    def test_declaration_mentions_name(self):
        dec = build_mimic_declaration(_CARD, "うさぎ")
        assert "うさぎ" in dec and "mimic off" in dec

    def test_declaration_low_confidence_prefix(self):
        low = dict(_CARD, confidence="low")
        dec = build_mimic_declaration(low, "うさぎ")
        assert "自信ない" in dec
