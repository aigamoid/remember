"""bot.py - moimoichan Discord Bot エントリポイント

使い方:
    cp .env.example .env          # DISCORD_TOKEN を記入
    cp config.yml.example config.yml
    pip install -r requirements.txt
    python bot.py

応答は waiwai-oracle APIサーバ（src/api.py）から取得する。
APIはステートレスのため会話履歴は保持しない（conversation_id 廃止）。
"""

import asyncio
import os
import sys
from pathlib import Path

import discord
import yaml
from dotenv import load_dotenv

from oracle_client import OracleClient

_MAX_REPLY_LEN = 2000  # Discord 文字数制限


def _load_config() -> dict:
    path = Path(__file__).parent / "config.yml"
    if not path.exists():
        print("エラー: config.yml が見つかりません。config.yml.example をコピーして作成してください。")
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class MoimoichanBot(discord.Client):
    def __init__(self, oracle: OracleClient, cfg: dict) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.oracle = oracle
        self.cfg = cfg

    async def on_ready(self) -> None:
        print(f"[INFO] Logged in as {self.user} (id={self.user.id})")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None:
            return  # DMには応答しない（guild単位のRAGのため）
        if not self._should_respond(message):
            return

        query = self._extract_query(message)
        if not query:
            await message.reply("何か聞いてみてね！っ 🎤")
            return

        user = f"{message.channel.id}:{message.author.id}"

        async with message.channel.typing():
            try:
                answer = await self.oracle.chat(
                    query, str(message.guild.id), user
                )
                reply = answer[:_MAX_REPLY_LEN]
                await message.reply(reply or "……（何も思いつかなかった！っ 😅）")
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


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        print("エラー: DISCORD_TOKEN が未設定です (.env を確認してください)")
        sys.exit(1)

    cfg = _load_config()
    oracle_cfg = cfg.get("oracle", {})
    api_url = os.getenv("ORACLE_API_URL") or oracle_cfg.get("api_url", "")
    timeout = oracle_cfg.get("chat_timeout", 90)
    if not api_url:
        print("エラー: ORACLE_API_URL も config.yml の oracle.api_url も未設定です")
        sys.exit(1)

    oracle = OracleClient(base_url=api_url, timeout=timeout)
    bot = MoimoichanBot(oracle=oracle, cfg=cfg)
    bot.run(token)


if __name__ == "__main__":
    main()
