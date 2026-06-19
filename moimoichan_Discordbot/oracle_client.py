"""oracle_client.py - waiwai-oracle APIクライアント（非同期）

自前 RAG APIサーバ（src/api.py）の POST /chat を呼び出す。
Dify 廃止に伴い dify_client.py を置き換えたもの。
"""

from __future__ import annotations

import aiohttp


class OracleClient:
    def __init__(self, base_url: str, timeout: int = 90) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def chat(
        self,
        query: str,
        guild_id: str,
        user: str,
        guild_name: str | None = None,
        history: list[dict] | None = None,
        speaker: str | None = None,
    ) -> str:
        """質問を送り回答テキストを返す。

        history は直近の会話（{"role": "user"|"assistant", "content": str} の
        古い順リスト）。渡すとマルチターン回答になる（OI-10）。
        speaker は「いま話しかけている人」の表示名（任意・OI-22）。

        Raises:
            aiohttp.ClientResponseError: HTTP 4xx/5xx
            asyncio.TimeoutError: タイムアウト
        """
        payload = {"guild_id": str(guild_id), "query": query, "user": user}
        if guild_name:
            payload["guild_name"] = guild_name
        if history:
            payload["history"] = history
        if speaker:
            payload["speaker"] = speaker
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(f"{self._base}/chat", json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return data["answer"]

    async def remember(
        self,
        text: str,
        guild_id: str,
        user: str,
        speaker: str | None = None,
        channel_id: str | None = None,
    ) -> dict:
        """「覚えておいて」発話を /remember に送り、保存結果を返す（OI-24・書き込み）。

        戻り値: {"saved": bool, "subject": str|None, "content": str|None}

        Raises:
            aiohttp.ClientResponseError: HTTP 4xx/5xx
            asyncio.TimeoutError: タイムアウト
        """
        payload = {"guild_id": str(guild_id), "text": text, "user": user}
        if speaker:
            payload["speaker"] = speaker
        if channel_id:
            payload["channel_id"] = str(channel_id)
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(f"{self._base}/remember", json=payload) as resp:
                resp.raise_for_status()
                return await resp.json()
