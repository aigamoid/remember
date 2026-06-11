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
        self, query: str, guild_id: str, user: str, guild_name: str | None = None
    ) -> str:
        """質問を送り回答テキストを返す。

        Raises:
            aiohttp.ClientResponseError: HTTP 4xx/5xx
            asyncio.TimeoutError: タイムアウト
        """
        payload = {"guild_id": str(guild_id), "query": query, "user": user}
        if guild_name:
            payload["guild_name"] = guild_name
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(f"{self._base}/chat", json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return data["answer"]
