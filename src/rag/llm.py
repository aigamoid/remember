"""OpenRouter（OpenAI互換API）チャットLLM呼び出し。src/rag/engine.py から使用。

Kimi K2 が chain-of-thought を <think>...</think> で返すことがあるため除去する
（moimoichan_Discordbot/dify_client.py と同じ対策）。
"""

from __future__ import annotations

import re

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def strip_think(text: str) -> str:
    """LLM の <think>...</think> タグを除去する。"""
    return _THINK_RE.sub("", text).strip()


class ChatLLM:
    """OpenAI互換 chat.completions クライアントの薄いラッパー。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        client=None,
    ) -> None:
        if client is None:
            import openai

            client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._client = client

    async def complete(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content or ""
        return strip_think(content)
