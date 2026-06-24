"""moimoichan_Discordbot/bot.py の /oracle help（OI-27）のテスト。

ヘルプは静的テキスト（_HELP 定数）なので、DB も Discord 接続も使わず軽く検証する。
bot.py はパッケージ内の `from oracle_client import ...` / `from store import ...` を
使うため、Bot ディレクトリを sys.path に足してから import する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BOT_DIR = Path(__file__).resolve().parents[1] / "moimoichan_Discordbot"
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

bot = pytest.importorskip("bot")  # discord 等が無い環境では skip


def test_help_lists_all_commands():
    """ヘルプ本文に主要コマンドが一通り含まれること。"""
    text = bot._HELP
    for cmd in ("allow", "allowall", "deny", "sync", "status", "help"):
        assert f"/oracle {cmd}" in text


def test_help_describes_onboarding_flow():
    """導入フロー（許可→取り込み→メンションで質問）の要素が含まれること。"""
    text = bot._HELP
    assert "メンション" in text
    assert "sync" in text
    assert "remember" in text  # 管理ポータルの案内


def test_oracle_group_has_help_command():
    """OracleGroup に help コマンドが登録されていること（store は使わないので None でよい）。"""
    group = bot.OracleGroup(store=None)
    names = {cmd.name for cmd in group.commands}
    assert "help" in names


def test_oracle_group_has_mimic_commands():
    """#49: OracleGroup に mimic / mimic_off が登録されていること。"""
    group = bot.OracleGroup(store=None)
    names = {cmd.name for cmd in group.commands}
    assert "mimic" in names
    assert "mimic_off" in names


def test_help_mentions_mimic():
    """#49: ヘルプに真似っこ関連コマンドが載っていること。"""
    text = bot._HELP
    assert "/oracle mimic" in text
    assert "mimic_optout" in text
