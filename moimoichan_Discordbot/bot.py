"""bot.py - moimoichan Discord Bot エントリポイント

使い方:
    cp .env.example .env          # DISCORD_TOKEN / DIFY_CHAT_APP_KEY を記入
    cp config.yml.example config.yml
    pip install -r requirements.txt
    python bot.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import discord
import yaml
from dotenv import load_dotenv

from dify_client import DifyClient

_TTL_SECONDS = 3600   # 会話 TTL: 60 分
_MAX_ENTRIES = 500    # 会話キャッシュ上限
_MAX_REPLY_LEN = 2000 # Discord 文字数制限


def _load_config() -> dict:
    path = Path(__file__).parent / "config.yml"
    if not path.exists():
        print("エラー: config.yml が見つかりません。config.yml.example をコピーして作成してください。")
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class MoimoichanBot(discord.Client):
    def __init__(self, dify: DifyClient, cfg: dict) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.dify = dify
        self.cfg = cfg
        # key: (channel_id, user_id)  value: (conversation_id, last_updated)
        self.conversations: dict[tuple[int, int], tuple[str, float]] = {}

    async def on_ready(self) -> None:
        print(f"[INFO] Logged in as {self.user} (id={self.user.id})")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not self._should_respond(message):
            return

        query = self._extract_query(message)
        if not query:
            await message.reply("何か聞いてみてね！っ 🎤")
            return

        key = (message.channel.id, message.author.id)
        conv_id = self._get_conv_id(key)
        dify_user = f"{message.channel.id}:{message.author.id}"

        async with message.channel.typing():
            try:
                answer, new_conv_id = await self.dify.chat(query, conv_id, dify_user)
                self._set_conv_id(key, new_conv_id)
                reply = answer[:_MAX_REPLY_LEN] if len(answer) > _MAX_REPLY_LEN else answer
                await message.reply(reply)
            except asyncio.TimeoutError:
                print(f"[TIMEOUT] channel={message.channel.id} user={message.author.id}")
                try:
                    await message.reply("⏱️ 応答がタイムアウトしました。もう一度試してみてください！っ")
                except Exception:
                    pass
            except Exception as e:
                print(f"[ERROR] {type(e).__name__}: {e}")
                try:
                    await message.reply("⚠️ エラーが発生しました。もう一度試してみてね！っ")
                except Exception:
                    pass

    # ---- 内部ヘルパー ----

    def _should_respond(self, message: discord.Message) -> bool:
        dcfg = self.cfg.get("discord", {})
        channel_ids = dcfg.get("trigger_channel_ids") or []
        if channel_ids and message.channel.id not in channel_ids:
            return False
        if dcfg.get("mention_only", True) and self.user not in message.mentions:
            return False
        return True

    def _extract_query(self, message: discord.Message) -> str:
        text = message.content
        if self.user:
            text = text.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "")
        return text.strip()

    def _get_conv_id(self, key: tuple[int, int]) -> str:
        entry = self.conversations.get(key)
        if entry is None:
            return ""
        conv_id, ts = entry
        if time.time() - ts > _TTL_SECONDS:
            del self.conversations[key]
            return ""
        return conv_id

    def _set_conv_id(self, key: tuple[int, int], conv_id: str) -> None:
        self.conversations[key] = (conv_id, time.time())
        if len(self.conversations) > _MAX_ENTRIES:
            oldest = min(self.conversations, key=lambda k: self.conversations[k][1])
            del self.conversations[oldest]


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "")
    chat_key = os.getenv("DIFY_CHAT_APP_KEY", "")
    if not token:
        print("エラー: DISCORD_TOKEN が未設定です (.env を確認してください)")
        sys.exit(1)
    if not chat_key:
        print("エラー: DIFY_CHAT_APP_KEY が未設定です (.env を確認してください)")
        sys.exit(1)

    cfg = _load_config()
    endpoint = cfg.get("dify", {}).get("api_endpoint", "")
    timeout = cfg.get("dify", {}).get("chat_timeout", 90)
    if not endpoint:
        print("エラー: config.yml に dify.api_endpoint が設定されていません")
        sys.exit(1)

    dify = DifyClient(endpoint=endpoint, api_key=chat_key, timeout=timeout)
    bot = MoimoichanBot(dify=dify, cfg=cfg)
    bot.run(token)


if __name__ == "__main__":
    main()
