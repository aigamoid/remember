"""src/api.py のテスト（フェイクRagEngine + FastAPI TestClient）"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import build_engine, create_app
from src.trace import TraceRecorder


@pytest.fixture(autouse=True)
def _clear_api_token_env(monkeypatch):
    """テストでは ORACLE_API_TOKEN の有無を各ケースで明示する。"""
    monkeypatch.delenv("ORACLE_API_TOKEN", raising=False)


class FakeEngine:
    def __init__(
        self,
        memory_enabled: bool = False,
        extracted: dict | None = None,
        mimic_enabled: bool = False,
        persona_card: dict | None = None,
    ) -> None:
        self.calls: list[tuple] = []
        self.memory_enabled = memory_enabled
        self._extracted = extracted
        self.extract_calls: list[tuple] = []
        # 真似っこ（#49）
        self.mimic_enabled = mimic_enabled
        self.mimic_sample_limit = 300
        self._persona_card = persona_card
        self.persona_calls: list[tuple] = []
        self.last_channel_id: str | None = None

    async def answer(
        self,
        guild_id: str,
        query: str,
        guild_name: str | None = None,
        user_id: str | None = None,
        history: list[dict] | None = None,
        speaker_name: str | None = None,
        channel_id: str | None = None,
    ) -> dict:
        self.calls.append(
            (guild_id, query, guild_name, user_id, history, speaker_name)
        )
        self.last_channel_id = channel_id
        return {
            "answer": "テスト回答！っ",
            "rewritten_query": "書き換え済み",
            "sources": [{"channel_name": "general", "anchor_timestamp": "t", "score": 0.9}],
        }

    async def extract_memory(
        self, guild_id: str, text: str,
        speaker_name: str | None = None, user_id: str | None = None,
    ) -> dict | None:
        self.extract_calls.append((guild_id, text, speaker_name, user_id))
        return self._extracted

    async def build_persona_card(
        self, guild_id: str, display_name: str, samples: list[dict],
        user_id: str | None = None,
    ) -> dict | None:
        self.persona_calls.append((guild_id, display_name, len(samples), user_id))
        return self._persona_card


class FakeMimicStore:
    """/mimic/* 用のフェイク（DB I/O 無し・#49）。"""

    def __init__(
        self, consent: str = "unknown", samples: list[dict] | None = None,
        name: str | None = "うさぎ",
    ) -> None:
        self._consent = consent
        self._samples = samples if samples is not None else [{"content": "やっほ〜"}]
        self._name = name
        self.saved: list[tuple] = []
        self.states: list[tuple] = []
        self.cleared: list[tuple] = []
        self.consent_set: list[tuple] = []

    def get_consent(self, guild_id, author_id):
        return self._consent

    def set_consent(self, guild_id, author_id, consent):
        self.consent_set.append((guild_id, author_id, consent))

    def fetch_samples(self, guild_id, author_id, limit=300):
        return self._samples

    def resolve_name(self, guild_id, author_id):
        return self._name

    def save_card(self, guild_id, author_id, display_name, card, sample_count, created_by=None):
        self.saved.append((guild_id, author_id, display_name, card, sample_count))

    def set_state(self, guild_id, channel_id, author_id, started_by=None):
        self.states.append((guild_id, channel_id, author_id, started_by))

    def clear_state(self, guild_id, channel_id):
        self.cleared.append((guild_id, channel_id))
        return True


@pytest.fixture
def client():
    return TestClient(create_app(engine=FakeEngine()))


_BASE_CFG = {
    "qdrant": {"url": "http://localhost:6333", "collection": "c"},
    "embedding": {"model": "text-embedding-3-small", "dimensions": 1536},
    "rag": {},
}


@pytest.fixture
def _fake_api_keys(monkeypatch):
    """build_engine は ChatLLM/Embedder の OpenAI クライアントを構築する。
    CI にはキーが無いのでダミーを入れて構築だけ通す（ネットワークは張らない）。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")


class TestBuildEngineTrace:
    def test_trace_recorder_wired_when_enabled(self, _fake_api_keys):
        cfg = {**_BASE_CFG, "rag": {"debug_trace": True}}
        engine = build_engine(cfg)
        assert engine.trace_enabled is True
        assert isinstance(engine.trace_recorder, TraceRecorder)

    def test_no_trace_recorder_when_disabled(self, _fake_api_keys):
        cfg = {**_BASE_CFG, "rag": {"debug_trace": False}}
        engine = build_engine(cfg)
        assert engine.trace_enabled is False
        assert engine.trace_recorder is None

    def test_trace_off_by_default(self, _fake_api_keys):
        engine = build_engine(_BASE_CFG)
        assert engine.trace_enabled is False
        assert engine.trace_recorder is None


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestApiToken:
    """Bot→API 共有シークレット認証（OI-45 / #38）。"""

    def _client(self, token):
        return TestClient(create_app(engine=FakeEngine(), api_token=token))

    def test_chat_rejects_missing_token_when_configured(self):
        client = self._client("secret")
        resp = client.post("/chat", json={"guild_id": "g1", "query": "質問"})
        assert resp.status_code == 401

    def test_chat_rejects_wrong_token(self):
        client = self._client("secret")
        resp = client.post(
            "/chat",
            json={"guild_id": "g1", "query": "質問"},
            headers={"X-Oracle-Token": "nope"},
        )
        assert resp.status_code == 401

    def test_chat_accepts_correct_token(self):
        client = self._client("secret")
        resp = client.post(
            "/chat",
            json={"guild_id": "g1", "query": "質問"},
            headers={"X-Oracle-Token": "secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["answer"] == "テスト回答！っ"

    def test_remember_rejects_missing_token_when_configured(self):
        client = TestClient(create_app(
            engine=FakeEngine(memory_enabled=True, extracted={"subject": "s", "content": "c"}),
            memory_saver=lambda *a: True,
            api_token="secret",
        ))
        resp = client.post("/remember", json={"guild_id": "g1", "text": "x覚えて"})
        assert resp.status_code == 401

    def test_remember_accepts_correct_token(self):
        client = TestClient(create_app(
            engine=FakeEngine(memory_enabled=True, extracted={"subject": "s", "content": "c"}),
            memory_saver=lambda *a: True,
            api_token="secret",
        ))
        resp = client.post(
            "/remember",
            json={"guild_id": "g1", "text": "x覚えて"},
            headers={"X-Oracle-Token": "secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["saved"] is True

    def test_health_open_without_token(self):
        client = self._client("secret")
        assert client.get("/health").status_code == 200

    def test_no_token_configured_allows_requests(self):
        # 後方互換: ORACLE_API_TOKEN 未設定なら従来どおり認証なしで通る（fail-open）
        client = TestClient(create_app(engine=FakeEngine(), api_token=None))
        resp = client.post(
            "/chat", json={"guild_id": "g1", "query": "質問"}
        )
        assert resp.status_code == 200


class TestChat:
    def test_chat_returns_answer(self, client):
        resp = client.post(
            "/chat", json={"guild_id": "g1", "query": "こんにちは"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "テスト回答！っ"
        assert body["rewritten_query"] == "書き換え済み"
        assert body["sources"][0]["channel_name"] == "general"

    def test_chat_passes_guild_id(self):
        engine = FakeEngine()
        client = TestClient(create_app(engine=engine))
        client.post("/chat", json={"guild_id": "g99", "query": "質問"})
        assert engine.calls == [("g99", "質問", None, None, None, None)]

    def test_chat_passes_guild_name(self):
        engine = FakeEngine()
        client = TestClient(create_app(engine=engine))
        client.post(
            "/chat",
            json={"guild_id": "g99", "query": "質問", "guild_name": "テストサーバー"},
        )
        assert engine.calls == [("g99", "質問", "テストサーバー", None, None, None)]

    def test_chat_parses_user_id_from_user_field(self):
        engine = FakeEngine()
        client = TestClient(create_app(engine=engine))
        client.post(
            "/chat",
            json={"guild_id": "g99", "query": "質問", "user": "ch1:u42"},
        )
        assert engine.calls == [("g99", "質問", None, "u42", None, None)]

    def test_chat_passes_history(self):
        engine = FakeEngine()
        client = TestClient(create_app(engine=engine))
        hist = [
            {"role": "user", "content": "前q"},
            {"role": "assistant", "content": "前a"},
        ]
        client.post(
            "/chat",
            json={"guild_id": "g1", "query": "それ詳しく", "history": hist},
        )
        assert engine.calls == [("g1", "それ詳しく", None, None, hist, None)]

    def test_chat_passes_speaker(self):
        # OI-22: speaker フィールドが engine.answer の speaker_name へ素通しされる
        engine = FakeEngine()
        client = TestClient(create_app(engine=engine))
        client.post(
            "/chat",
            json={"guild_id": "g1", "query": "質問", "speaker": "まめぽん"},
        )
        assert engine.calls == [("g1", "質問", None, None, None, "まめぽん")]

    def test_empty_query_rejected(self, client):
        resp = client.post("/chat", json={"guild_id": "g1", "query": "   "})
        assert resp.status_code == 422

    def test_missing_guild_id_rejected(self, client):
        resp = client.post("/chat", json={"query": "質問"})
        assert resp.status_code == 422

    def test_user_field_optional(self, client):
        resp = client.post(
            "/chat",
            json={"guild_id": "g1", "query": "質問", "user": "ch1:u1"},
        )
        assert resp.status_code == 200


class TestQuota:
    def test_over_quota_returns_message_without_calling_engine(self):
        engine = FakeEngine()
        client = TestClient(create_app(
            engine=engine,
            quota_checker=lambda gid: "本日の上限に達しました🙏",
        ))
        resp = client.post("/chat", json={"guild_id": "g1", "query": "質問"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "本日の上限に達しました🙏"
        assert body["sources"] == []
        assert engine.calls == []  # 回答LLMを呼ばない＝コスト発生なし

    def test_under_quota_calls_engine(self):
        engine = FakeEngine()
        client = TestClient(create_app(
            engine=engine,
            quota_checker=lambda gid: None,  # 上限内
        ))
        resp = client.post("/chat", json={"guild_id": "g1", "query": "質問"})
        assert resp.status_code == 200
        assert resp.json()["answer"] == "テスト回答！っ"
        assert engine.calls == [("g1", "質問", None, None, None, None)]

    def test_quota_checker_receives_guild_id(self):
        seen = []
        client = TestClient(create_app(
            engine=FakeEngine(),
            quota_checker=lambda gid: seen.append(gid) or None,
        ))
        client.post("/chat", json={"guild_id": "g42", "query": "質問"})
        assert seen == ["g42"]


class TestRemember:
    def _client(self, memory_enabled, extracted, saver=None, records=None):
        engine = FakeEngine(memory_enabled=memory_enabled, extracted=extracted)
        if saver is None and records is not None:
            def saver(*args):
                records.append(args)
                return True
        return TestClient(create_app(engine=engine, memory_saver=saver)), engine

    def test_disabled_returns_not_saved(self):
        # rag.memory_enabled OFF（engine.memory_enabled=False）なら抽出も保存もしない
        client, engine = self._client(False, {"subject": "x", "content": "y"})
        resp = client.post("/remember", json={"guild_id": "g1", "text": "xはy覚えて"})
        assert resp.status_code == 200
        assert resp.json()["saved"] is False
        assert engine.extract_calls == []

    def test_no_fact_returns_not_saved(self):
        records = []
        client, engine = self._client(True, None, records=records)
        resp = client.post("/remember", json={"guild_id": "g1", "text": "いい曲覚えて"})
        assert resp.json()["saved"] is False
        assert records == []  # 保存は呼ばれない

    def test_saves_extracted_fact(self):
        records = []
        client, engine = self._client(
            True, {"subject": "かにじる", "content": "ケーキが好き"}, records=records
        )
        resp = client.post("/remember", json={
            "guild_id": "g1", "text": "かにじるはケーキ好き覚えて",
            "speaker": "うさ", "user": "ch1:u9", "channel_id": "ch1",
        })
        assert resp.json() == {
            "saved": True, "subject": "かにじる", "content": "ケーキが好き"
        }
        # saver には (guild_id, content, subject, created_by, source_channel_id)
        assert records == [("g1", "ケーキが好き", "かにじる", "u9", "ch1")]
        # extract_memory に speaker / user_id が渡る
        assert engine.extract_calls == [("g1", "かにじるはケーキ好き覚えて", "うさ", "u9")]

    def test_save_failure_returns_not_saved(self):
        client, engine = self._client(
            True, {"subject": None, "content": "x"}, saver=lambda *a: False
        )
        resp = client.post("/remember", json={"guild_id": "g1", "text": "x覚えて"})
        assert resp.json()["saved"] is False

    def test_empty_text_rejected(self):
        client, engine = self._client(True, None)
        resp = client.post("/remember", json={"guild_id": "g1", "text": "   "})
        assert resp.status_code == 422


class TestChatChannelId:
    """#49: /chat が channel_id を engine.answer へ素通しする（新フィールド正典＋user後方互換）。"""

    def test_channel_id_field_passthrough(self):
        engine = FakeEngine()
        client = TestClient(create_app(engine=engine))
        client.post(
            "/chat",
            json={"guild_id": "g1", "query": "q", "channel_id": "ch9"},
        )
        assert engine.last_channel_id == "ch9"

    def test_channel_id_fallback_from_user(self):
        engine = FakeEngine()
        client = TestClient(create_app(engine=engine))
        client.post(
            "/chat",
            json={"guild_id": "g1", "query": "q", "user": "ch1:u42"},
        )
        assert engine.last_channel_id == "ch1"

    def test_channel_id_field_wins_over_user(self):
        engine = FakeEngine()
        client = TestClient(create_app(engine=engine))
        client.post(
            "/chat",
            json={"guild_id": "g1", "query": "q", "user": "ch1:u42", "channel_id": "ch9"},
        )
        assert engine.last_channel_id == "ch9"


_SUCCESS_CARD = {
    "nicknames": ["うさ"], "personality": "明るくマイペース", "likes": ["ゲーム"],
    "speech_style": "語尾に〜っす", "catchphrases": ["っす"], "confidence": "high",
}


class TestMimicEndpoints:
    """#49: /mimic/start|stop|optout。"""

    def _app(self, engine, store):
        return TestClient(create_app(engine=engine, mimic_store=store))

    def test_start_disabled_returns_not_started(self):
        engine = FakeEngine(mimic_enabled=False, persona_card=_SUCCESS_CARD)
        client = self._app(engine, FakeMimicStore())
        resp = client.post(
            "/mimic/start",
            json={"guild_id": "g1", "target_id": "u2", "channel_id": "c1"},
        )
        assert resp.json()["started"] is False

    def test_start_optout_blocks(self):
        engine = FakeEngine(mimic_enabled=True, persona_card=_SUCCESS_CARD)
        store = FakeMimicStore(consent="optout")
        client = self._app(engine, store)
        resp = client.post(
            "/mimic/start",
            json={"guild_id": "g1", "target_id": "u2", "channel_id": "c1"},
        )
        body = resp.json()
        assert body["started"] is False and body["reason"]
        # optout は素材取得もカード生成もしない（コスト0）
        assert engine.persona_calls == []
        assert store.saved == []

    def test_start_no_samples_returns_not_started(self):
        engine = FakeEngine(mimic_enabled=True, persona_card=_SUCCESS_CARD)
        store = FakeMimicStore(samples=[])
        client = self._app(engine, store)
        resp = client.post(
            "/mimic/start",
            json={"guild_id": "g1", "target_id": "u2", "channel_id": "c1"},
        )
        assert resp.json()["started"] is False

    def test_start_empty_card_returns_not_started(self):
        engine = FakeEngine(mimic_enabled=True, persona_card=None)
        store = FakeMimicStore()
        client = self._app(engine, store)
        resp = client.post(
            "/mimic/start",
            json={"guild_id": "g1", "target_id": "u2", "channel_id": "c1"},
        )
        assert resp.json()["started"] is False
        assert store.saved == []

    def test_start_success(self):
        engine = FakeEngine(mimic_enabled=True, persona_card=_SUCCESS_CARD)
        store = FakeMimicStore(name="うさぎ")
        client = self._app(engine, store)
        resp = client.post(
            "/mimic/start",
            json={
                "guild_id": "g1", "target_id": "u2", "channel_id": "c1",
                "target_name": "うさぎ", "user": "c1:admin",
            },
        )
        body = resp.json()
        assert body["started"] is True
        assert body["declaration"] and "うさぎ" in body["declaration"]
        assert store.saved and store.saved[0][1] == "u2"
        assert store.states and store.states[0] == ("g1", "c1", "u2", "admin")

    def test_stop_clears_state(self):
        store = FakeMimicStore()
        client = self._app(FakeEngine(mimic_enabled=True), store)
        resp = client.post(
            "/mimic/stop", json={"guild_id": "g1", "channel_id": "c1"}
        )
        assert resp.json()["stopped"] is True
        assert store.cleared == [("g1", "c1")]

    def test_optout_sets_consent(self):
        store = FakeMimicStore()
        client = self._app(FakeEngine(mimic_enabled=True), store)
        resp = client.post(
            "/mimic/optout", json={"guild_id": "g1", "target_id": "u2"}
        )
        assert resp.json()["ok"] is True
        assert store.consent_set == [("g1", "u2", "optout")]
