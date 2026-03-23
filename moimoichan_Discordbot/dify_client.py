"""dify_client.py - Dify Chat API クライアント（非同期）

POST /v1/chat-messages で「わいわいちゃん」に問い合わせる。
"""

import asyncio
import aiohttp


class DifyClient:
    def __init__(self, endpoint: str, api_key: str, timeout: int = 90) -> None:
        # endpoint は /v1 まで含む形式 (例: http://host/v1)
        self._base = endpoint.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def chat(
        self,
        query: str,
        conversation_id: str,
        user: str,
    ) -> tuple[str, str]:
        """Dify にメッセージを送り (answer, conversation_id) を返す。

        Args:
            query: ユーザーの発言テキスト
            conversation_id: 継続会話の ID。新規は空文字 ""
            user: Dify API の user フィールド（"channel_id:user_id" 形式）

        Returns:
            (answer テキスト, conversation_id)

        Raises:
            aiohttp.ClientResponseError: HTTP 4xx/5xx
            asyncio.TimeoutError: タイムアウト
        """
        payload = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "conversation_id": conversation_id,
            "user": user,
        }
        url = f"{self._base}/chat-messages"

        async with aiohttp.ClientSession(
            headers=self._headers,
            timeout=self._timeout,
        ) as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()

        answer = data.get("answer", "")
        new_conv_id = data.get("conversation_id", conversation_id)
        return answer, new_conv_id
