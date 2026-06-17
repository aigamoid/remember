"""src/cli.py のテスト（requests をモンキーパッチ）"""

from __future__ import annotations

import pytest
import requests

import src.cli as cli


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


SAMPLE = {
    "answer": "テスト回答！っ",
    "rewritten_query": "書き換え済みクエリ",
    "sources": [
        {"channel_name": "general", "anchor_timestamp": "t1", "score": 0.9},
        {"channel_name": "general", "anchor_timestamp": "t2", "score": 0.8},
        {"channel_name": "雑談", "anchor_timestamp": "t3", "score": 0.7},
    ],
}


class TestCheckHealth:
    def test_ok(self, monkeypatch):
        monkeypatch.setattr(
            cli.requests, "get", lambda url, timeout: FakeResponse(200)
        )
        assert cli.check_health("http://x:8000") is True

    def test_http_error(self, monkeypatch):
        monkeypatch.setattr(
            cli.requests, "get", lambda url, timeout: FakeResponse(500)
        )
        assert cli.check_health("http://x:8000") is False

    def test_connection_error(self, monkeypatch):
        def boom(url, timeout):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(cli.requests, "get", boom)
        assert cli.check_health("http://x:8000") is False


class TestChatOnce:
    def test_posts_payload_and_adds_elapsed(self, monkeypatch):
        captured = {}

        def fake_post(url, json, timeout):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse(200, dict(SAMPLE))

        monkeypatch.setattr(cli.requests, "post", fake_post)
        result = cli.chat_once("http://x:8000/", "g1", "質問")

        assert captured["url"] == "http://x:8000/chat"
        assert captured["json"] == {
            "guild_id": "g1", "query": "質問", "user": "cli",
        }
        assert result["answer"] == "テスト回答！っ"
        assert result["elapsed"] >= 0

    def test_no_history_key_when_absent(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            cli.requests, "post",
            lambda url, json, timeout: captured.update(json=json)
            or FakeResponse(200, dict(SAMPLE)),
        )
        cli.chat_once("http://x:8000", "g1", "質問")
        assert "history" not in captured["json"]

    def test_history_included_in_payload(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            cli.requests, "post",
            lambda url, json, timeout: captured.update(json=json)
            or FakeResponse(200, dict(SAMPLE)),
        )
        hist = [{"role": "user", "content": "前q"}]
        cli.chat_once("http://x:8000", "g1", "質問", history=hist)
        assert captured["json"]["history"] == hist

    def test_http_error_raises(self, monkeypatch):
        monkeypatch.setattr(
            cli.requests, "post", lambda url, json, timeout: FakeResponse(500)
        )
        with pytest.raises(requests.HTTPError):
            cli.chat_once("http://x:8000", "g1", "質問")


class TestFormatResult:
    def test_contains_answer_and_rewritten(self):
        out = cli.format_result({**SAMPLE, "elapsed": 1.23})
        assert "テスト回答！っ" in out
        assert "書き換え済みクエリ" in out

    def test_footer_has_sources_and_time(self):
        out = cli.format_result({**SAMPLE, "elapsed": 1.23})
        assert "ソース 3 件" in out
        assert "1.2秒" in out

    def test_channels_deduplicated(self):
        out = cli.format_result({**SAMPLE, "elapsed": 0.0})
        assert out.count("general") == 1

    def test_no_sources(self):
        out = cli.format_result(
            {"answer": "a", "rewritten_query": "q", "sources": []}
        )
        assert "ソース 0 件" in out
