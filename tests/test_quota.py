"""src/quota.py のテスト（純関数・DB不要）"""

from __future__ import annotations

from datetime import datetime, timezone

from src import quota


class TestJstDayStart:
    def test_returns_utc_iso_of_jst_midnight(self):
        # 2026-06-18 02:00 JST → その日のJST 0時 = 2026-06-17 15:00 UTC
        now = datetime(2026, 6, 18, 2, 0, tzinfo=quota.JST)
        assert quota.jst_day_start_utc_iso(now) == "2026-06-17T15:00:00+00:00"

    def test_just_after_jst_midnight(self):
        now = datetime(2026, 6, 18, 0, 5, tzinfo=quota.JST)
        assert quota.jst_day_start_utc_iso(now) == "2026-06-17T15:00:00+00:00"

    def test_late_night_jst_still_same_day(self):
        now = datetime(2026, 6, 18, 23, 59, tzinfo=quota.JST)
        assert quota.jst_day_start_utc_iso(now) == "2026-06-17T15:00:00+00:00"

    def test_accepts_utc_input(self):
        # 2026-06-17 16:00 UTC = 2026-06-18 01:00 JST → JST 0時 = 06-17 15:00 UTC
        now = datetime(2026, 6, 17, 16, 0, tzinfo=timezone.utc)
        assert quota.jst_day_start_utc_iso(now) == "2026-06-17T15:00:00+00:00"


class TestQuestionQuota:
    def test_under_limit_ok(self):
        assert quota.question_quota_exceeded(19, 20) is False

    def test_at_limit_blocked(self):
        assert quota.question_quota_exceeded(20, 20) is True

    def test_over_limit_blocked(self):
        assert quota.question_quota_exceeded(25, 20) is True


class TestChannelLimit:
    def test_under_limit_ok(self):
        assert quota.channel_limit_exceeded(0, 1) is False

    def test_at_limit_blocked(self):
        assert quota.channel_limit_exceeded(1, 1) is True

    def test_none_limit_is_unlimited(self):
        assert quota.channel_limit_exceeded(9999, None) is False


class TestMessages:
    def test_daily_message_contains_limit_and_reset(self):
        m = quota.daily_limit_message(20)
        assert "20問" in m and "0時" in m

    def test_daily_message_with_upgrade(self):
        up = {"display_name": "Pro", "price_jpy": 700, "daily_question_limit": 80,
              "channel_limit": 10}
        m = quota.daily_limit_message(20, up)
        assert "Pro" in m and "700" in m and "80問/日" in m

    def test_channel_message_with_unlimited_upgrade(self):
        up = {"display_name": "MAX", "price_jpy": 1500, "daily_question_limit": 200,
              "channel_limit": None}
        m = quota.channel_limit_message(10, up)
        assert "10個" in m and "MAX" in m and "全チャンネル" in m

    def test_no_upgrade_no_suffix(self):
        m = quota.daily_limit_message(200, None)
        assert "アップグレード" not in m
