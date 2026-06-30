"""src/db.py の Stripe 課金まわり（OI-14 D）のDBテスト。

実Postgres（conn フィクスチャ）に対して実行する。未起動なら skip。
"""

from __future__ import annotations

import pytest

from src import db


# ---- plan_defs.stripe_price_id ----

def test_update_plan_def_sets_and_reads_price_id(conn):
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700,
                       stripe_price_id="price_pro_123")
    plan = db.get_plan_def(conn, "pro")
    assert plan["stripe_price_id"] == "price_pro_123"
    # fetch_plan_defs にも乗る
    pro = next(p for p in db.fetch_plan_defs(conn) if p["plan_key"] == "pro")
    assert pro["stripe_price_id"] == "price_pro_123"


def test_update_plan_def_empty_price_id_is_null(conn):
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700, stripe_price_id="  ")
    assert db.get_plan_def(conn, "pro")["stripe_price_id"] is None


def test_update_plan_def_rejects_duplicate_price_id(conn):
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700,
                       stripe_price_id="price_dup")
    with pytest.raises(db.DuplicatePriceIdError):
        db.update_plan_def(conn, "max", "MAX", None, 200, 1500,
                           stripe_price_id="price_dup")
    # max 側は変更されていない（拒否で commit されない）
    assert db.get_plan_def(conn, "max")["stripe_price_id"] is None


def test_get_plan_by_price_id(conn):
    db.update_plan_def(conn, "pro", "Pro", 10, 80, 700,
                       stripe_price_id="price_pro_xyz")
    plan = db.get_plan_by_price_id(conn, "price_pro_xyz")
    assert plan is not None and plan["plan_key"] == "pro"
    assert db.get_plan_by_price_id(conn, "price_unknown") is None
    assert db.get_plan_by_price_id(conn, "") is None


# ---- guild_plans の Stripe 自動更新 ----

def test_update_guild_subscription_inserts_and_reads(conn):
    updated = db.update_guild_subscription(
        conn, "g1", plan_key="pro", status="active",
        stripe_customer_id="cus_1", stripe_subscription_id="sub_1",
        current_period_end="2026-07-01T00:00:00+00:00",
    )
    assert updated is True
    info = db.get_guild_billing(conn, "g1")
    assert info["plan_key"] == "pro"
    assert info["status"] == "active"
    assert info["stripe_subscription_id"] == "sub_1"
    # 実効プランにも反映
    assert db.get_guild_plan(conn, "g1")["plan_key"] == "pro"


def test_get_guild_by_subscription(conn):
    db.update_guild_subscription(
        conn, "g2", plan_key="pro", status="active",
        stripe_subscription_id="sub_abc",
    )
    found = db.get_guild_by_subscription(conn, "sub_abc")
    assert found is not None and found["guild_id"] == "g2"
    assert db.get_guild_by_subscription(conn, "sub_none") is None
    assert db.get_guild_by_subscription(conn, "") is None


def test_canceled_is_not_revived_by_late_update(conn):
    """subscription.deleted で canceled 後に古い updated が来ても復活しない。"""
    db.update_guild_subscription(
        conn, "g3", plan_key="pro", status="active",
        stripe_subscription_id="sub_3",
    )
    db.update_guild_subscription(
        conn, "g3", plan_key="free", status="canceled",
        stripe_subscription_id="sub_3",
    )
    # 後着の active 系イベント → ガードでスキップ
    updated = db.update_guild_subscription(
        conn, "g3", plan_key="pro", status="active",
        stripe_subscription_id="sub_3",
    )
    assert updated is False
    assert db.get_guild_billing(conn, "g3")["status"] == "canceled"


def test_older_period_end_is_ignored(conn):
    """current_period_end が DB 既存値より古いイベントは無視する（順不同対策）。"""
    db.update_guild_subscription(
        conn, "g4", plan_key="pro", status="active",
        current_period_end="2026-08-01T00:00:00+00:00",
    )
    updated = db.update_guild_subscription(
        conn, "g4", plan_key="pro", status="past_due",
        current_period_end="2026-07-01T00:00:00+00:00",  # 古い
    )
    assert updated is False
    info = db.get_guild_billing(conn, "g4")
    assert info["status"] == "active"
    assert info["current_period_end"] == "2026-08-01T00:00:00+00:00"


def test_update_guild_subscription_is_idempotent(conn):
    """同値の再送（冪等）。2回呼んでも壊れない。"""
    for _ in range(2):
        db.update_guild_subscription(
            conn, "g5", plan_key="pro", status="active",
            stripe_subscription_id="sub_5",
            current_period_end="2026-07-01T00:00:00+00:00",
        )
    assert db.get_guild_billing(conn, "g5")["plan_key"] == "pro"


def test_billing_overview_includes_stripe(conn):
    db.upsert_guild(conn, "g6", "Guild6")
    db.update_guild_subscription(
        conn, "g6", plan_key="pro", status="active",
        stripe_customer_id="cus_6", stripe_subscription_id="sub_6",
    )
    from src import quota
    rows = db.fetch_billing_overview(conn, quota.jst_day_start_utc_iso())
    g6 = next(r for r in rows if r["guild_id"] == "g6")
    assert g6["stripe_customer_id"] == "cus_6"
    assert g6["stripe_subscription_id"] == "sub_6"
