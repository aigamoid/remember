"""src/admin の認証・ログインフローのテスト（DB不要の範囲）"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.admin import auth
from src.admin.app import COOKIE_NAME, create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    return TestClient(create_app(), follow_redirects=False)


# ── 認証トークン ─────────────────────────────────────────────────────────────

class TestAuth:
    def test_password_ok(self, monkeypatch):
        monkeypatch.setenv("ADMIN_PASSWORD", "secret")
        assert auth.password_ok("secret")
        assert not auth.password_ok("wrong")

    def test_password_unset_always_false(self, monkeypatch):
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        assert not auth.password_ok("anything")

    def test_token_roundtrip(self, monkeypatch):
        monkeypatch.setenv("ADMIN_PASSWORD", "secret")
        assert auth.verify_token(auth.make_token())

    def test_expired_token_invalid(self, monkeypatch):
        monkeypatch.setenv("ADMIN_PASSWORD", "secret")
        assert not auth.verify_token(auth.make_token(ttl_seconds=-10))

    def test_tampered_signature_invalid(self, monkeypatch):
        monkeypatch.setenv("ADMIN_PASSWORD", "secret")
        exp, _sig = auth.make_token().rsplit(".", 1)
        assert not auth.verify_token(f"{exp}.deadbeef")

    def test_none_token_invalid(self):
        assert not auth.verify_token(None)


# ── ログインフロー ───────────────────────────────────────────────────────────

class TestLoginFlow:
    def test_login_page_renders(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "パスワード" in resp.text

    def test_dashboard_redirects_when_unauthed(self, client):
        resp = client.get("/")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_wrong_password_rejected(self, client):
        resp = client.post("/login", data={"password": "wrong"})
        assert resp.status_code == 401

    def test_correct_password_sets_cookie(self, client):
        resp = client.post("/login", data={"password": "secret"})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        assert COOKIE_NAME in resp.cookies

    def test_logout_redirects_to_login(self, client):
        resp = client.get("/logout")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"


# ── 記憶の承認画面（#56 案C）。認証ゲートを確認（DB happy path は test_db でカバー）─────

class TestMemoriesRoutes:
    def test_memories_redirects_when_unauthed(self, client):
        resp = client.get("/memories")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_approve_requires_auth(self, client):
        resp = client.post("/memories/approve", data={"candidate_id": 1})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_reject_requires_auth(self, client):
        resp = client.post("/memories/reject", data={"candidate_id": 1})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_delete_requires_auth(self, client):
        resp = client.post(
            "/memories/delete", data={"guild_id": "g1", "memory_id": 1}
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
