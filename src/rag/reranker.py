"""Jina Reranker クライアント（OI-9: 検索結果のリランキング）。src/rag/engine.py から使用。

dense 検索で多めに取った候補を cross-encoder で関連度順に並べ替え、上位だけを回答に渡す。
APIキー（JINA_API_KEY）未設定・API失敗時は engine 側が dense 順にフォールバックする
（リランクは品質向上のための任意機能で、無くても回答は止まらない）。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_JINA_URL = "https://api.jina.ai/v1/rerank"
_DEFAULT_MODEL = "jina-reranker-v2-base-multilingual"


@dataclass
class RerankResult:
    """order: documents のインデックスを関連度の高い順に並べたもの（最大 top_k 件）。
    total_tokens: 課金計測用（レスポンスから取れなければ 0）。"""

    order: list[int]
    total_tokens: int = 0


class Reranker:
    def __init__(
        self,
        api_key: str | None,
        model: str = _DEFAULT_MODEL,
        url: str = _JINA_URL,
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._url = url
        self._timeout = timeout
        self._client = client  # テスト時に MockTransport 付き client を差し込める

    @property
    def model(self) -> str:
        return self._model

    async def rerank(
        self, query: str, documents: list[str], top_k: int
    ) -> RerankResult:
        """documents を query との関連度で並べ替え、上位 top_k のインデックスを返す。

        失敗時は例外を送出する（呼び出し側で dense 順にフォールバックする想定）。
        """
        if not documents:
            return RerankResult(order=[], total_tokens=0)
        if not self._api_key:
            raise RuntimeError("JINA_API_KEY が未設定です")

        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": min(top_k, len(documents)),
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.post(self._url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._client is None:
                await client.aclose()

        order = [item["index"] for item in data.get("results", [])]
        total_tokens = (data.get("usage") or {}).get("total_tokens", 0)
        return RerankResult(order=order, total_tokens=total_tokens)
