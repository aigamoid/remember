"""dify_client.py - Dify Chat API クライアント（非同期・SSE streaming）

POST /v1/chat-messages で「わいわいちゃん」に問い合わせる。
advanced-chat (Chatflow) アプリは blocking モードに既知の不具合があるため
streaming (SSE) モードを使用する。

Chatflow の SSE イベント構造:
- message: answer フィールドはトークン単位のデルタ（累積ではない）
- workflow_finished: data.outputs.answer に完全な回答テキスト
- message_end は送信されない（通常 Chat アプリとの違い）
"""

import asyncio
import json
import re
import aiohttp

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class DifyClient:
    def __init__(self, endpoint: str, api_key: str, timeout: int = 90) -> None:
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

        SSE streaming モードでレスポンスを受信する。
        Chatflow では message イベントがデルタ送信、workflow_finished に
        完全な回答が入る。LLM の <think> タグは除去して返す。

        Raises:
            aiohttp.ClientResponseError: HTTP 4xx/5xx
            asyncio.TimeoutError: タイムアウト
            RuntimeError: Dify が error イベントを返した場合
        """
        payload = {
            "inputs": {},
            "query": query,
            "response_mode": "streaming",
            "conversation_id": conversation_id,
            "user": user,
        }
        url = f"{self._base}/chat-messages"

        chunks: list[str] = []
        new_conv_id = conversation_id

        async with aiohttp.ClientSession(
            headers=self._headers,
            timeout=self._timeout,
        ) as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                while True:
                    raw_line = await resp.content.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    event = data.get("event")
                    if event == "message":
                        chunks.append(data.get("answer", ""))
                        if not new_conv_id:
                            new_conv_id = data.get("conversation_id", "")
                    elif event == "workflow_finished":
                        outputs = data.get("data", {}).get("outputs", {})
                        full_answer = outputs.get("answer", "")
                        if full_answer:
                            return self._clean(full_answer), new_conv_id
                    elif event == "message_end":
                        new_conv_id = data.get("conversation_id", new_conv_id)
                    elif event == "error":
                        msg = data.get("message", "Unknown Dify error")
                        raise RuntimeError(f"Dify error: {msg}")

        # workflow_finished がなかった場合はデルタを結合して返す
        return self._clean("".join(chunks)), new_conv_id

    @staticmethod
    def _clean(text: str) -> str:
        """LLM の <think>...</think> タグを除去する。"""
        return _THINK_RE.sub("", text).strip()
