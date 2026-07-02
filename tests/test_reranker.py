"""src/rag/reranker.py のテスト（httpx MockTransport で Jina API を模擬・実通信なし）"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from src.rag.reranker import Reranker


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestReranker:
    def test_returns_order_and_tokens(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["query"] == "クエリ"
            assert body["documents"] == ["a", "b", "c"]
            assert body["top_n"] == 2  # min(top_k=2, len=3)
            assert request.headers["authorization"] == "Bearer k"
            return httpx.Response(200, json={
                "results": [{"index": 2}, {"index": 0}],
                "usage": {"total_tokens": 42},
            })

        rr = Reranker(api_key="k", client=_client(handler))
        res = asyncio.run(rr.rerank("クエリ", ["a", "b", "c"], top_k=2))
        assert res.order == [2, 0]
        assert res.total_tokens == 42

    def test_empty_documents_skips_call(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("空ドキュメントでは API を呼ばない")

        rr = Reranker(api_key="k", client=_client(handler))
        res = asyncio.run(rr.rerank("q", [], top_k=5))
        assert res.order == []

    def test_missing_api_key_raises(self):
        rr = Reranker(api_key=None)
        with pytest.raises(RuntimeError):
            asyncio.run(rr.rerank("q", ["a"], top_k=1))

    def test_http_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limit"})

        rr = Reranker(api_key="k", client=_client(handler))
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(rr.rerank("q", ["a"], top_k=1))

    def test_missing_usage_defaults_zero(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": [{"index": 0}]})

        rr = Reranker(api_key="k", client=_client(handler))
        res = asyncio.run(rr.rerank("q", ["a"], top_k=1))
        assert res.order == [0]
        assert res.total_tokens == 0
