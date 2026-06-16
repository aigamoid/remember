"""src/formatter.py のテスト（純粋関数・DB不要）"""

from __future__ import annotations

from src.formatter import format_message_line, resolve_mentions

_MAP = {"111": "アリス", "222": "ボブ"}


class TestResolveMentions:
    def test_replaces_known_id(self):
        assert resolve_mentions("やあ <@111>", _MAP) == "やあ @アリス"

    def test_replaces_nickname_form(self):
        # <@!ID> 形式（ニックネーム表記）も解決する
        assert resolve_mentions("<@!222> どう？", _MAP) == "@ボブ どう？"

    def test_multiple_mentions(self):
        out = resolve_mentions("<@111> と <@222>", _MAP)
        assert out == "@アリス と @ボブ"

    def test_unknown_id_left_as_is(self):
        assert resolve_mentions("<@999>", _MAP) == "<@999>"

    def test_empty_map_returns_original(self):
        assert resolve_mentions("<@111>", {}) == "<@111>"

    def test_no_mention_unchanged(self):
        assert resolve_mentions("ふつうの文", _MAP) == "ふつうの文"

    def test_role_and_channel_mentions_untouched(self):
        # <@&ID>（ロール）/ <#ID>（チャンネル）はユーザーメンションではないので対象外
        assert resolve_mentions("<@&111> <#222>", _MAP) == "<@&111> <#222>"


class TestFormatMessageLineWithMap:
    _TS = "2024-01-01T00:00:00+00:00"

    def test_resolves_mention_in_content(self):
        line = format_message_line("user", "<@111> おはよう", self._TS, False, 9, _MAP)
        assert "@アリス おはよう" in line
        assert "<@111>" not in line

    def test_no_map_keeps_raw_id(self):
        line = format_message_line("user", "<@111> おはよう", self._TS, False, 9)
        assert "<@111>" in line
