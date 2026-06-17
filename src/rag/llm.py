"""OpenRouter（OpenAI互換API）チャットLLM呼び出し。src/rag/engine.py から使用。

Kimi K2 が chain-of-thought を <think>...</think> で返すことがあるため除去する
（moimoichan_Discordbot/dify_client.py と同じ対策）。

complete() は本文に加え token 使用量（usage）を返す（src/usage.py がコスト計上に使う）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def strip_think(text: str) -> str:
    """LLM の <think>...</think> タグを除去する。"""
    return _THINK_RE.sub("", text).strip()


@dataclass
class Usage:
    """LLM/embedding 呼び出し1回分のトークン使用量。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class Completion:
    """complete() の戻り値。本文(text)と使用量(usage)。"""

    text: str
    model: str = ""
    usage: Usage = field(default_factory=Usage)


def _extract_usage(resp) -> Usage:
    """OpenAI互換レスポンスから usage を取り出す（無ければ 0）。"""
    u = getattr(resp, "usage", None)
    if u is None:
        return Usage()
    return Usage(
        prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(u, "completion_tokens", 0) or 0,
        total_tokens=getattr(u, "total_tokens", 0) or 0,
    )


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
    ) -> Completion:
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
        return Completion(
            text=strip_think(content), model=model, usage=_extract_usage(resp)
        )
