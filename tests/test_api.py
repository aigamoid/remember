"""src/api.py のテスト（フェイクRagEngine + FastAPI TestClient）"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import create_app


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, str | None]] = []

    async def answer(
        self,
        guild_id: str,
        query: str,
        guild_name: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        self.calls.append((guild_id, query, guild_name, user_id))
        return {
            "answer": "テスト回答！っ",
            "rewritten_query": "書き換え済み",
            "sources": [{"channel_name": "general", "anchor_timestamp": "t", "score": 0.9}],
        }


@pytest.fixture
def client():
    return TestClient(create_app(engine=FakeEngine()))


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


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
        assert engine.calls == [("g99", "質問", None, None)]

    def test_chat_passes_guild_name(self):
        engine = FakeEngine()
        client = TestClient(create_app(engine=engine))
        client.post(
            "/chat",
            json={"guild_id": "g99", "query": "質問", "guild_name": "テストサーバー"},
        )
        assert engine.calls == [("g99", "質問", "テストサーバー", None)]

    def test_chat_parses_user_id_from_user_field(self):
        engine = FakeEngine()
        client = TestClient(create_app(engine=engine))
        client.post(
            "/chat",
            json={"guild_id": "g99", "query": "質問", "user": "ch1:u42"},
        )
        assert engine.calls == [("g99", "質問", None, "u42")]

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
        assert engine.calls == [("g1", "質問", None, None)]

    def test_quota_checker_receives_guild_id(self):
        seen = []
        client = TestClient(create_app(
            engine=FakeEngine(),
            quota_checker=lambda gid: seen.append(gid) or None,
        ))
        client.post("/chat", json={"guild_id": "g42", "query": "質問"})
        assert seen == ["g42"]
