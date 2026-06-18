"""プラン上限（quota）の判定と利用者向け案内文。OI-14 C-2。

DBアクセスは含まない純ロジック（テストしやすい）。実際のカウントは src/db.py、
判定の組み立ては src/api.py（質問の日次上限）と Bot（チャンネル数上限）が行う。
上限到達時の挙動は「ハードストップ＋翌日リセット＋アップグレード案内」(プランA)。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def jst_day_start_utc_iso(now: datetime | None = None) -> str:
    """『今日(JST)の0時』を UTC ISO8601 文字列で返す。usage_log.created_at と比較する。"""
    now = now or datetime.now(JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    start_jst = now.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    return start_jst.astimezone(timezone.utc).isoformat()


def question_quota_exceeded(used_today: int, daily_limit: int) -> bool:
    """本日の質問数が上限以上か（上限以上なら回答停止）。"""
    return used_today >= daily_limit


def channel_limit_exceeded(current_count: int, channel_limit: int | None) -> bool:
    """許可チャンネル数が上限以上か。channel_limit が None なら無制限（常に False）。"""
    if channel_limit is None:
        return False
    return current_count >= channel_limit


def _upgrade_suffix(upgrade: dict | None, axis: str) -> str:
    """アップグレード案内の付加文。axis: 'questions' | 'channels'。"""
    if not upgrade:
        return ""
    if axis == "questions":
        detail = f"{upgrade['daily_question_limit']}問/日"
    else:
        cl = upgrade.get("channel_limit")
        detail = "全チャンネル" if cl is None else f"{cl}チャンネル"
    return (
        f"\nもっと使うには **{upgrade['display_name']}プラン**"
        f"（¥{upgrade['price_jpy']}/月・{detail}）へのアップグレードがおすすめです。"
    )


def daily_limit_message(daily_limit: int, upgrade: dict | None = None) -> str:
    """質問の日次上限に達したときの案内文（プランA）。"""
    return (
        f"本日の質問上限（{daily_limit}問）に達しました🙏 "
        f"日本時間の0時にリセットされます。" + _upgrade_suffix(upgrade, "questions")
    )


def channel_limit_message(channel_limit: int, upgrade: dict | None = None) -> str:
    """チャンネル取り込み上限に達したときの案内文（/oracle allow 拒否時）。"""
    return (
        f"このプランで取り込めるチャンネルは{channel_limit}個までです。"
        + _upgrade_suffix(upgrade, "channels")
    )
