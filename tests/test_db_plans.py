"""src/db.py のプラン管理(plan_defs/guild_plans)・quota集計のテスト（実Postgres）"""

from __future__ import annotations

from src.db import (
    allow_channel,
    count_allowed_channels,
    count_questions_since,
    fetch_billing_overview,
    fetch_plan_defs,
    get_guild_plan,
    get_plan_def,
    insert_usage,
    set_guild_plan,
    update_plan_def,
    upsert_guild,
)


class TestPlanDefsSeed:
    def test_initial_plans_seeded(self, conn):
        keys = {p["plan_key"] for p in fetch_plan_defs(conn)}
        assert keys == {"free", "pro", "max"}

    def test_free_defaults(self, conn):
        free = get_plan_def(conn, "free")
        assert free["channel_limit"] == 1
        assert free["daily_question_limit"] == 20
        assert free["price_jpy"] == 0

    def test_max_is_unlimited_channels(self, conn):
        assert get_plan_def(conn, "max")["channel_limit"] is None

    def test_update_plan_def(self, conn):
        update_plan_def(conn, "pro", "Pro", 15, 100, 800)
        pro = get_plan_def(conn, "pro")
        assert pro["channel_limit"] == 15
        assert pro["daily_question_limit"] == 100
        assert pro["price_jpy"] == 800


class TestGuildPlan:
    def test_default_is_free(self, conn):
        plan = get_guild_plan(conn, "g-unknown")
        assert plan["plan_key"] == "free"
        assert plan["daily_question_limit"] == 20
        assert plan["channel_limit"] == 1

    def test_set_and_get(self, conn):
        set_guild_plan(conn, "g-1", "pro", note="入金確認")
        plan = get_guild_plan(conn, "g-1")
        assert plan["plan_key"] == "pro"
        assert plan["daily_question_limit"] == 80
        assert plan["channel_limit"] == 10

    def test_set_overwrites(self, conn):
        set_guild_plan(conn, "g-1", "pro")
        set_guild_plan(conn, "g-1", "max")
        assert get_guild_plan(conn, "g-1")["plan_key"] == "max"


class TestQuotaCounts:
    def test_count_questions_since(self, conn):
        insert_usage(conn, "g-1", "answer", "m", 1, 1, 2, 0.0)
        insert_usage(conn, "g-1", "answer", "m", 1, 1, 2, 0.0)
        insert_usage(conn, "g-1", "rewrite", "m", 1, 1, 2, 0.0)  # answer以外は対象外
        insert_usage(conn, "g-2", "answer", "m", 1, 1, 2, 0.0)   # 別guildは対象外
        conn.commit()
        assert count_questions_since(conn, "g-1", "2000-01-01T00:00:00+00:00") == 2

    def test_count_questions_respects_since(self, conn):
        insert_usage(conn, "g-1", "answer", "m", 1, 1, 2, 0.0)
        conn.commit()
        # 未来の since 以降は0件
        assert count_questions_since(conn, "g-1", "2999-01-01T00:00:00+00:00") == 0

    def test_count_allowed_channels(self, conn):
        allow_channel(conn, "g-1", "ch1", "general", "admin")
        allow_channel(conn, "g-1", "ch2", "random", "admin")
        assert count_allowed_channels(conn, "g-1") == 2


class TestBillingOverview:
    def test_overview_shows_plan_and_usage(self, conn):
        upsert_guild(conn, "g-1", "サーバー1")
        set_guild_plan(conn, "g-1", "pro")
        allow_channel(conn, "g-1", "ch1", "general", "admin")
        insert_usage(conn, "g-1", "answer", "m", 1, 1, 2, 0.0)
        conn.commit()
        rows = {r["guild_id"]: r for r in
                fetch_billing_overview(conn, "2000-01-01T00:00:00+00:00")}
        g1 = rows["g-1"]
        assert g1["plan_key"] == "pro"
        assert g1["daily_question_limit"] == 80
        assert g1["channel_count"] == 1
        assert g1["used_today"] == 1

    def test_overview_unassigned_guild_is_free(self, conn):
        upsert_guild(conn, "g-2", "サーバー2")
        conn.commit()
        rows = {r["guild_id"]: r for r in
                fetch_billing_overview(conn, "2000-01-01T00:00:00+00:00")}
        assert rows["g-2"]["plan_key"] == "free"
        assert rows["g-2"]["channel_limit"] == 1
