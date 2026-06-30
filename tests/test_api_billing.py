"""src/api.py の課金ルート（/billing/checkout・/portal・/webhook・OI-14 D）のテスト。

billing.* と db.get_connection をモックし、DB なしで HTTP ステータスの出し分けを検証する。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import billing, db
from src.api import create_app


class _DummyConn:
    def close(self):
        pass


@pytest.fixture(autouse=True)
def _clear_token(monkeypatch):
    monkeypatch.delenv("ORACLE_API_TOKEN", raising=False)


@pytest.fixture
def client(monkeypatch):
    # engine を注入して startup の DB 初期化を回避する。
    app = create_app(engine=object())
    monkeypatch.setattr(db, "get_connection", lambda *a, **k: _DummyConn())
    monkeypatch.setattr(billing, "enabled", lambda: True)
    return TestClient(app)


# ---- checkout ----

def test_checkout_ok(client, monkeypatch):
    monkeypatch.setattr(
        billing, "create_checkout_session",
        lambda *a, **k: "https://checkout.test/cs",
    )
    r = client.post("/billing/checkout", json={"guild_id": "g1", "plan_key": "pro"})
    assert r.status_code == 200
    assert r.json()["url"] == "https://checkout.test/cs"


def test_checkout_already_subscribed_409(client, monkeypatch):
    def boom(*a, **k):
        raise billing.AlreadySubscribedError()
    monkeypatch.setattr(billing, "create_checkout_session", boom)
    r = client.post("/billing/checkout", json={"guild_id": "g1", "plan_key": "pro"})
    assert r.status_code == 409


def test_checkout_unknown_plan_400(client, monkeypatch):
    def boom(*a, **k):
        raise billing.UnknownPlanError()
    monkeypatch.setattr(billing, "create_checkout_session", boom)
    r = client.post("/billing/checkout", json={"guild_id": "g1", "plan_key": "x"})
    assert r.status_code == 400


def test_checkout_stripe_error_502(client, monkeypatch):
    def boom(*a, **k):
        raise billing.BillingError()
    monkeypatch.setattr(billing, "create_checkout_session", boom)
    r = client.post("/billing/checkout", json={"guild_id": "g1", "plan_key": "pro"})
    assert r.status_code == 502


def test_checkout_disabled_503(monkeypatch):
    app = create_app(engine=object())
    monkeypatch.setattr(billing, "enabled", lambda: False)
    c = TestClient(app)
    r = c.post("/billing/checkout", json={"guild_id": "g1", "plan_key": "pro"})
    assert r.status_code == 503


# ---- portal ----

def test_portal_ok(client, monkeypatch):
    monkeypatch.setattr(db, "get_guild_billing",
                        lambda *a, **k: {"stripe_customer_id": "cus_1"})
    monkeypatch.setattr(billing, "create_portal_session",
                        lambda *a, **k: "https://portal.test/ps")
    r = client.post("/billing/portal", json={"guild_id": "g1"})
    assert r.status_code == 200
    assert r.json()["url"] == "https://portal.test/ps"


def test_portal_no_subscription_404(client, monkeypatch):
    monkeypatch.setattr(db, "get_guild_billing", lambda *a, **k: None)
    r = client.post("/billing/portal", json={"guild_id": "g1"})
    assert r.status_code == 404


# ---- webhook ----

def test_webhook_ok(client, monkeypatch):
    monkeypatch.setattr(billing, "handle_event",
                        lambda *a, **k: {"handled": True})
    r = client.post("/billing/webhook", content=b"{}",
                    headers={"Stripe-Signature": "sig"})
    assert r.status_code == 200
    assert r.json()["received"] is True


def test_webhook_bad_signature_400(client, monkeypatch):
    def boom(*a, **k):
        raise billing.WebhookSignatureError()
    monkeypatch.setattr(billing, "handle_event", boom)
    r = client.post("/billing/webhook", content=b"{}",
                    headers={"Stripe-Signature": "bad"})
    assert r.status_code == 400


def test_webhook_retryable_503(client, monkeypatch):
    def boom(*a, **k):
        raise billing.WebhookRetryableError()
    monkeypatch.setattr(billing, "handle_event", boom)
    r = client.post("/billing/webhook", content=b"{}",
                    headers={"Stripe-Signature": "sig"})
    assert r.status_code == 503


def test_webhook_unexpected_500(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(billing, "handle_event", boom)
    r = client.post("/billing/webhook", content=b"{}",
                    headers={"Stripe-Signature": "sig"})
    assert r.status_code == 500


def test_webhook_disabled_503(monkeypatch):
    app = create_app(engine=object())
    monkeypatch.setattr(billing, "enabled", lambda: False)
    c = TestClient(app)
    r = c.post("/billing/webhook", content=b"{}",
               headers={"Stripe-Signature": "sig"})
    assert r.status_code == 503
