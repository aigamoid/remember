"""src/embedder.py のテスト（フェイクOpenAIクライアント・フェイクエンコーダ）"""

from __future__ import annotations

from src.embedder import _MAX_INPUT_TOKENS, Embedder


class FakeEncoder:
    """1文字=1トークンとして扱う単純なエンコーダ。"""

    def encode(self, text, disallowed_special=()):
        return list(text)

    def decode(self, tokens):
        return "".join(tokens)


class FakeEmbeddingData:
    def __init__(self, embedding):
        self.embedding = embedding


class FakeOpenAI:
    """embeddings.create の呼び出しを記録するフェイク。"""

    def __init__(self):
        self.inputs: list[list[str]] = []
        outer = self

        class _Embeddings:
            def create(self, model, input, dimensions):
                outer.inputs.append(input)

                class _Resp:
                    data = [FakeEmbeddingData([0.0] * dimensions) for _ in input]

                return _Resp()

        self.embeddings = _Embeddings()


def _embedder(client):
    return Embedder(dimensions=4, client=client, encoder=FakeEncoder())


class TestEmbed:
    def test_returns_one_vector_per_text(self):
        client = FakeOpenAI()
        vectors = _embedder(client).embed(["あ", "い"])
        assert len(vectors) == 2
        assert len(vectors[0]) == 4

    def test_empty_text_replaced_with_placeholder(self):
        client = FakeOpenAI()
        _embedder(client).embed(["", "   "])
        assert client.inputs[0] == [" ", " "]

    def test_long_text_truncated(self):
        client = FakeOpenAI()
        long_text = "あ" * (_MAX_INPUT_TOKENS + 500)
        _embedder(client).embed([long_text])
        assert len(client.inputs[0][0]) == _MAX_INPUT_TOKENS

    def test_short_text_not_truncated(self):
        client = FakeOpenAI()
        _embedder(client).embed(["短いテキスト"])
        assert client.inputs[0][0] == "短いテキスト"

    def test_embed_one_returns_single_vector(self):
        client = FakeOpenAI()
        vec = _embedder(client).embed_one("テスト")
        assert len(vec) == 4
