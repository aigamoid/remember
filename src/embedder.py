"""OpenAI Embedding API ラッパー。indexer.py / src/rag/engine.py から使用。

APIキーは環境変数 OPENAI_API_KEY を使用する（OpenRouter ではなく OpenAI 直）。
"""

from __future__ import annotations

import os


# text-embedding-3-small の入力上限は 8,192 トークン。マージンを取って切り詰める
_MAX_INPUT_TOKENS = 8000


class Embedder:
    """テキストをベクトルに変換する。"""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        client=None,
        encoder=None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._client = client
        self._encoder = encoder

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

    def _get_encoder(self):
        if self._encoder is None:
            import tiktoken

            self._encoder = tiktoken.get_encoding("cl100k_base")
        return self._encoder

    def _truncate(self, text: str) -> str:
        """埋め込みモデルの入力上限を超えるテキストを切り詰める。
        disallowed_special=() はチャットログ中の特殊トークン文字列でのエラー防止。"""
        tokens = self._get_encoder().encode(text, disallowed_special=())
        if len(tokens) <= _MAX_INPUT_TOKENS:
            return text
        return self._get_encoder().decode(tokens[:_MAX_INPUT_TOKENS])

    def embed(self, texts: list[str]) -> list[list[float]]:
        """テキストのリストをベクトルのリストに変換する（1回のAPI呼び出し）。"""
        # 空文字・空白のみは API エラーになるためプレースホルダに置換
        safe = [self._truncate(t) if t.strip() else " " for t in texts]
        resp = self._get_client().embeddings.create(
            model=self.model, input=safe, dimensions=self.dimensions
        )
        return [d.embedding for d in resp.data]

    def embed_one(self, text: str) -> list[float]:
        """単一テキストをベクトルに変換する。"""
        return self.embed([text])[0]

    def embed_one_with_usage(self, text: str) -> tuple[list[float], int]:
        """単一テキストを (ベクトル, 消費トークン数) で返す。
        src/rag/engine.py がクエリ embedding のコスト計上に使う。"""
        safe = self._truncate(text) if text.strip() else " "
        resp = self._get_client().embeddings.create(
            model=self.model, input=[safe], dimensions=self.dimensions
        )
        usage = getattr(resp, "usage", None)
        tokens = getattr(usage, "total_tokens", 0) or 0
        return resp.data[0].embedding, tokens
