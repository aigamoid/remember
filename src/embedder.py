"""OpenAI Embedding API ラッパー。indexer.py / src/rag/engine.py から使用。

APIキーは環境変数 OPENAI_API_KEY を使用する（OpenRouter ではなく OpenAI 直）。
"""

from __future__ import annotations

import os


class Embedder:
    """テキストをベクトルに変換する。"""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        client=None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._client = client

    def _get_client(self):
        if self._client is None:
            import openai

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY が未設定です (.env を確認してください)"
                )
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        """テキストのリストをベクトルのリストに変換する（1回のAPI呼び出し）。"""
        # 空文字・空白のみは API エラーになるためプレースホルダに置換
        safe = [t if t.strip() else " " for t in texts]
        resp = self._get_client().embeddings.create(
            model=self.model, input=safe, dimensions=self.dimensions
        )
        return [d.embedding for d in resp.data]

    def embed_one(self, text: str) -> list[float]:
        """単一テキストをベクトルに変換する。"""
        return self.embed([text])[0]
