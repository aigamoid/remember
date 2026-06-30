"""src/billing.py（Stripe 連携・OI-14 D）のテスト。

実 stripe パッケージは使わず、billing.stripe をフェイクへ差し替えてロジックを検証する。
DB 更新の確認には実Postgres（conn フィクスチャ）を使う（未起動なら skip）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import billing, db


# ---- フェイク Stripe ----

class _FakeError(Exception):
    pass


class _FakeSigError(_FakeError):
    pass


class FakeStripe:
    """billing が使う stripe API の最小モック。"""

    def __init__(self):
        self.api_key = None
        self._event = None          # construct_event が返すイベント
        self._raise_sig = False     # True なら署名エラー
        self._subscriptions = {}    # sub_id -> sub dict
        self.created_sessions = []
        self.created_portals = []

        outer = self

        class _Session:
            @staticmethod
            def create(**kwargs):
                outer.created_sessions.append(kwargs)
                return SimpleNamespace(url="https://checkout.stripe.test/cs_1")

        class _Portal:
            @staticmethod
            def create(**kwargs):
                outer.created_portals.append(kwargs)
                return SimpleNamespace(url="https://portal.stripe.test/ps_1")

        class _Webhook:
            @staticmethod
            def construct_event(payload, sig_header, secret):
                if outer._raise_sig:
                    raise _FakeSigError("bad sig")
                return outer._event

        class _Subscription:
            @staticmethod
            def retrieve(sub_id):
                return outer._subscriptions[sub_id]

        self.checkout = SimpleNamespace(Session=_Session)
        self.billing_portal = SimpleNamespace(Session=_Portal)
        self.Webhook = _Webhook
        self.Subscription = _Subscription
        self.error = SimpleNamespace(
            StripeError=_FakeError, SignatureVerificationError=_FakeSigError
        )


def _make_sub(sub_id, price_id, status="active", customer="cus_1",
              period_end=1_780_000_000):
    return {
        "id": sub_id,
        "status": status,
        "customer": customer,
        "current_period_end": period_end,
        "items": {"data": [{"price": {"id": price_id}}]},
    }


@pytest.fixture
def fake_stripe(monkeypatch):
    fs = FakeStripe()
    monkeypatch.setattr(billing, "stripe", fs)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    return fs


# ---- enabled / status mapping ----

def test_enabled_false_without_key(monkeypatch):
    monkeypatch.setattr(billing, "stripe", FakeStripe())
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert billing.enabled() is False


def test_enabled_false_without_sdk(monkeypatch):
    monkeypatch.setattr(billing, "stripe", None)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    assert billing.enabled() is False


def test_enabled_true(fake_stripe):
    assert billing.enabled() is True


@pytest.mark.parametrize("stripe_status,expected", [
    ("active", "active"), ("trialing", "active"),
    ("past_due", "past_due"), ("unpaid", "past_due"),
    ("incomplete", "past_due"), ("paused", "past_due"),
    ("canceled", "canceled"), ("incomplete_expired", "canceled"),
])
def test_map_status(stripe_status, expected):
    assert billing._map_status(stripe_status) == expected


# ---- checkout / portal ----

def test_create_checkout_returns_url(fake_stripe, conn):
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700,
                       stripe_price_id="price_pro")
    url = billing.create_checkout_session(
        conn, "g1", "pro", "https://ok", "https://cancel"
    )
    assert url == "https://checkout.stripe.test/cs_1"
    kwargs = fake_stripe.created_sessions[0]
    assert kwargs["metadata"]["guild_id"] == "g1"
    assert kwargs["subscription_data"]["metadata"]["guild_id"] == "g1"
    assert kwargs["idempotency_key"] == "upgrade:g1:pro"


def test_create_checkout_unknown_plan(fake_stripe, conn):
    # stripe_price_id 未設定の plan は弾く
    with pytest.raises(billing.UnknownPlanError):
        billing.create_checkout_session(conn, "g1", "free", "u", "c")


def test_create_checkout_already_subscribed(fake_stripe, conn):
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700,
                       stripe_price_id="price_pro")
    db.update_guild_subscription(
        conn, "g1", plan_key="pro", status="active",
        stripe_subscription_id="sub_1",
    )
    with pytest.raises(billing.AlreadySubscribedError):
        billing.create_checkout_session(conn, "g1", "pro", "u", "c")


def test_create_portal_returns_url(fake_stripe):
    url = billing.create_portal_session("cus_1", "https://back")
    assert url == "https://portal.stripe.test/ps_1"


def test_disabled_raises(monkeypatch, conn):
    monkeypatch.setattr(billing, "stripe", None)
    with pytest.raises(billing.BillingDisabledError):
        billing.create_checkout_session(conn, "g1", "pro", "u", "c")


# ---- webhook: 署名 ----

def test_webhook_signature_error(fake_stripe, conn):
    fake_stripe._raise_sig = True
    with pytest.raises(billing.WebhookSignatureError):
        billing.handle_event(conn, b"{}", "bad")


# ---- webhook: イベント別 ----

def test_checkout_completed_upgrades(fake_stripe, conn):
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700,
                       stripe_price_id="price_pro")
    fake_stripe._subscriptions["sub_1"] = _make_sub("sub_1", "price_pro")
    fake_stripe._event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"guild_id": "g1", "plan_key": "pro"},
            "client_reference_id": "g1",
            "subscription": "sub_1",
        }},
    }
    res = billing.handle_event(conn, b"{}", "sig")
    assert res["handled"] is True
    info = db.get_guild_billing(conn, "g1")
    assert info["plan_key"] == "pro" and info["status"] == "active"
    assert info["stripe_subscription_id"] == "sub_1"


def test_subscription_updated_syncs_status(fake_stripe, conn):
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700,
                       stripe_price_id="price_pro")
    db.update_guild_subscription(
        conn, "g1", plan_key="pro", status="active",
        stripe_subscription_id="sub_1",
    )
    fake_stripe._event = {
        "type": "customer.subscription.updated",
        "data": {"object": _make_sub("sub_1", "price_pro", status="past_due")},
    }
    billing.handle_event(conn, b"{}", "sig")
    assert db.get_guild_billing(conn, "g1")["status"] == "past_due"


def test_subscription_updated_unknown_guild_retryable(fake_stripe, conn):
    # まだ guild に紐付いていない sub の updated → 再送させる（5xx）
    fake_stripe._event = {
        "type": "customer.subscription.updated",
        "data": {"object": _make_sub("sub_unlinked", "price_pro")},
    }
    with pytest.raises(billing.WebhookRetryableError):
        billing.handle_event(conn, b"{}", "sig")


def test_subscription_updated_metadata_fallback(fake_stripe, conn):
    """逆引き不可でも subscription.metadata.guild_id があれば処理できる。"""
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700,
                       stripe_price_id="price_pro")
    sub = _make_sub("sub_meta", "price_pro")
    sub["metadata"] = {"guild_id": "gmeta"}
    fake_stripe._event = {
        "type": "customer.subscription.updated",
        "data": {"object": sub},
    }
    billing.handle_event(conn, b"{}", "sig")
    assert db.get_guild_billing(conn, "gmeta")["plan_key"] == "pro"


def test_subscription_deleted_downgrades_to_free(fake_stripe, conn):
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700,
                       stripe_price_id="price_pro")
    db.update_guild_subscription(
        conn, "g1", plan_key="pro", status="active",
        stripe_subscription_id="sub_1",
    )
    fake_stripe._event = {
        "type": "customer.subscription.deleted",
        "data": {"object": _make_sub("sub_1", "price_pro", status="canceled")},
    }
    billing.handle_event(conn, b"{}", "sig")
    info = db.get_guild_billing(conn, "g1")
    assert info["plan_key"] == "free" and info["status"] == "canceled"


def test_payment_failed_sets_past_due(fake_stripe, conn):
    db.update_guild_subscription(
        conn, "g1", plan_key="pro", status="active",
        stripe_subscription_id="sub_1",
    )
    fake_stripe._event = {
        "type": "invoice.payment_failed",
        "data": {"object": {"subscription": "sub_1"}},
    }
    billing.handle_event(conn, b"{}", "sig")
    info = db.get_guild_billing(conn, "g1")
    assert info["status"] == "past_due"
    assert info["plan_key"] == "pro"  # plan は維持（回答継続）


def test_unknown_price_does_not_change_plan(fake_stripe, conn):
    # price_id が plan_defs に無い → plan を変えずに 200 相当
    db.update_guild_subscription(
        conn, "g1", plan_key="pro", status="active",
        stripe_subscription_id="sub_1",
    )
    fake_stripe._event = {
        "type": "customer.subscription.updated",
        "data": {"object": _make_sub("sub_1", "price_GHOST")},
    }
    res = billing.handle_event(conn, b"{}", "sig")
    assert res["reason"] == "unknown_price"
    assert db.get_guild_billing(conn, "g1")["plan_key"] == "pro"


def test_unhandled_event_ignored(fake_stripe, conn):
    fake_stripe._event = {"type": "customer.created", "data": {"object": {}}}
    res = billing.handle_event(conn, b"{}", "sig")
    assert res["handled"] is False


# ---- 遷移結合テスト（completed → updated → deleted）----

def test_full_lifecycle(fake_stripe, conn):
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700,
                       stripe_price_id="price_pro")

    # 1) checkout 完了 → pro active
    fake_stripe._subscriptions["sub_1"] = _make_sub(
        "sub_1", "price_pro", period_end=1_780_000_000
    )
    fake_stripe._event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"guild_id": "gL"}, "subscription": "sub_1",
        }},
    }
    billing.handle_event(conn, b"{}", "sig")
    assert db.get_guild_billing(conn, "gL")["plan_key"] == "pro"

    # 2) subscription.updated（期間更新・新しい period_end）
    fake_stripe._event = {
        "type": "customer.subscription.updated",
        "data": {"object": _make_sub(
            "sub_1", "price_pro", status="active", period_end=1_790_000_000
        )},
    }
    billing.handle_event(conn, b"{}", "sig")
    assert db.get_guild_billing(conn, "gL")["status"] == "active"

    # 3) subscription.deleted → free/canceled
    fake_stripe._event = {
        "type": "customer.subscription.deleted",
        "data": {"object": _make_sub(
            "sub_1", "price_pro", status="canceled", period_end=1_790_000_001
        )},
    }
    billing.handle_event(conn, b"{}", "sig")
    info = db.get_guild_billing(conn, "gL")
    assert info["plan_key"] == "free" and info["status"] == "canceled"
