"""oracle_client.py - waiwai-oracle APIクライアント（非同期）

自前 RAG APIサーバ（src/api.py）の POST /chat を呼び出す。
Dify 廃止に伴い dify_client.py を置き換えたもの。
"""

from __future__ import annotations

import aiohttp


class OracleClient:
    def __init__(
        self, base_url: str, timeout: int = 90, api_token: str | None = None
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        # Bot→API の共有シークレット（OI-45）。設定時は X-Oracle-Token として送る。
        self._headers = {"X-Oracle-Token": api_token} if api_token else {}

    async def chat(
        self,
        query: str,
        guild_id: str,
        user: str,
        guild_name: str | None = None,
        history: list[dict] | None = None,
        speaker: str | None = None,
        channel_id: str | None = None,
    ) -> str:
        """質問を送り回答テキストを返す。

        history は直近の会話（{"role": "user"|"assistant", "content": str} の
        古い順リスト）。渡すとマルチターン回答になる（OI-10）。user 発言には
        任意で "speaker"（発話者の表示名）を含められ、別の人の発言と区別される（#63）。
        speaker は「いま話しかけている人」の表示名（任意・OI-22）。
        channel_id は真似っこモードの状態解決に使う（任意・#49）。

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
        if channel_id:
            payload["channel_id"] = str(channel_id)
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(
                f"{self._base}/chat", json=payload, headers=self._headers
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return data["answer"]

    async def _post(self, path: str, payload: dict) -> dict:
        """共通 POST ヘルパー（#49 の /mimic/* 用）。"""
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(
                f"{self._base}{path}", json=payload, headers=self._headers
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def mimic_start(
        self,
        guild_id: str,
        target_id: str,
        channel_id: str,
        target_name: str | None = None,
        user: str | None = None,
    ) -> dict:
        """真似を開始する（#49）。戻り値: {started, declaration?, reason?, sample_count}。"""
        payload = {
            "guild_id": str(guild_id),
            "target_id": str(target_id),
            "channel_id": str(channel_id),
        }
        if target_name:
            payload["target_name"] = target_name
        if user:
            payload["user"] = user
        return await self._post("/mimic/start", payload)

    async def mimic_stop(self, guild_id: str, channel_id: str) -> dict:
        """その channel の真似を解除する（#49）。戻り値: {stopped}。"""
        return await self._post(
            "/mimic/stop",
            {"guild_id": str(guild_id), "channel_id": str(channel_id)},
        )

    async def mimic_optout(
        self, guild_id: str, target_id: str, user: str | None = None
    ) -> dict:
        """本人を真似対象から除外する（#49）。戻り値: {ok}。"""
        payload = {"guild_id": str(guild_id), "target_id": str(target_id)}
        if user:
            payload["user"] = user
        return await self._post("/mimic/optout", payload)

    async def _post_status(self, path: str, payload: dict) -> tuple[int, dict]:
        """raise せず (status, body) を返す POST（課金系・ステータスで案内を出し分ける）。"""
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(
                f"{self._base}{path}", json=payload, headers=self._headers
            ) as resp:
                try:
                    body = await resp.json()
                except Exception:
                    body = {}
                return resp.status, body

    async def create_checkout(
        self, guild_id: str, plan_key: str
    ) -> tuple[int, dict]:
        """サブスク申込の Checkout URL を要求する（OI-14 D）。戻り値: (status, body)。

        status: 200=成功(body['url']) / 409=既に契約中 / 400=不正プラン /
                503=課金未設定 / 502=Stripeエラー。
        """
        return await self._post_status(
            "/billing/checkout",
            {"guild_id": str(guild_id), "plan_key": plan_key},
        )

    async def billing_portal(self, guild_id: str) -> tuple[int, dict]:
        """解約・カード変更用の Customer Portal URL を要求する（OI-14 D）。

        status: 200=成功(body['url']) / 404=未契約 / 503=課金未設定 / 502=Stripeエラー。
        """
        return await self._post_status(
            "/billing/portal", {"guild_id": str(guild_id)}
        )

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
            async with session.post(
                f"{self._base}/remember", json=payload, headers=self._headers
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
