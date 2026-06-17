"""bot.py - moimoichan Discord Bot エントリポイント

使い方:
    cp .env.example .env          # DISCORD_TOKEN を記入
    cp config.yml.example config.yml
    pip install -r requirements.txt
    python bot.py

応答は waiwai-oracle APIサーバ（src/api.py）から取得する。
APIはステートレスだが、Bot がチャンネルごとに直近の会話を覚えて毎回 history として
渡すことでマルチターン対応している（OI-10。旧 conversation_id 方式は廃止済み）。

管理者向けスラッシュコマンド（サーバー管理権限が必要）:
    /oracle allow <channel>  チャンネルの読み取りを許可して取り込みを開始（opt-in）
    /oracle deny <channel>   許可を取り消し、取り込み済みデータを削除
    /oracle sync             許可チャンネルの差分取り込みを今すぐ実行
    /oracle status           取り込み状況を表示

実際の取り込み処理は worker.py（ジョブキュー経由）が行う。
"""

import asyncio
import os
import sys
from collections import deque
from pathlib import Path

import discord
import yaml
from discord import app_commands
from dotenv import load_dotenv

from oracle_client import OracleClient
from store import Store

_MAX_REPLY_LEN = 2000  # Discord 文字数制限
_DEFAULT_HISTORY_MAX_TURNS = 5  # チャンネルごとに覚えておく直近やり取り数（OI-10）

_JOB_STATUS_LABEL = {
    "queued": "⏳ 待機中",
    "running": "🏃 実行中",
    "done": "✅ 完了",
    "error": "⚠️ エラー",
}

_WELCOME = (
    "はじめまして、わいわいちゃんだよ！っ 🎤\n"
    "このサーバーの過去ログを覚えて質問に答えられるようになるけど、"
    "**許可されたチャンネルしか読まない**から安心してね。\n"
    "サーバー管理権限を持つ人が `/oracle allow #チャンネル` で読んでいい"
    "チャンネルを教えてくれたら、取り込みを始めるよ！っ"
)


def _load_config() -> dict:
    path = Path(__file__).parent / "config.yml"
    if not path.exists():
        print("エラー: config.yml が見つかりません。config.yml.example をコピーして作成してください。")
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class OracleGroup(app_commands.Group):
    """/oracle 管理コマンド群。DBへの書き込みと取り込みジョブの投入のみ行い、
    実処理はワーカーに任せる。"""

    def __init__(self, store: Store) -> None:
        super().__init__(
            name="oracle",
            description="過去ログ取り込みの管理（サーバー管理権限が必要）",
            default_permissions=discord.Permissions(manage_guild=True),
            guild_only=True,
        )
        self.store = store

    @app_commands.command(name="allow", description="チャンネルの読み取りを許可して取り込みを開始する")
    @app_commands.describe(channel="読み取りを許可するテキストチャンネル")
    async def allow(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        await self.store.register_guild(guild_id, interaction.guild.name)
        job_id = await self.store.allow_channel(
            guild_id, str(channel.id), channel.name, str(interaction.user.id)
        )
        note = (
            "取り込みを始めるね！終わったら質問できるよ。"
            if job_id is not None
            else "取り込みはもう予約済みだから、そのまま待っててね。"
        )
        await interaction.followup.send(
            f"✅ {channel.mention} の読み取りを許可したよ！っ {note}", ephemeral=True
        )

    @app_commands.command(name="deny", description="チャンネルの許可を取り消し、取り込み済みデータを削除する")
    @app_commands.describe(channel="許可を取り消すテキストチャンネル")
    async def deny(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        removed = await self.store.deny_channel(
            str(interaction.guild_id), str(channel.id), str(interaction.user.id)
        )
        head = (
            f"🚫 {channel.mention} の許可を取り消したよ。"
            if removed
            else f"{channel.mention} は許可されてなかったよ。"
        )
        await interaction.followup.send(
            f"{head} 取り込み済みデータの削除も予約したからね！っ", ephemeral=True
        )

    @app_commands.command(name="sync", description="許可チャンネルの新着メッセージを今すぐ取り込む")
    async def sync(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        status = await self.store.status(guild_id)
        if not status["allowed"]:
            await interaction.followup.send(
                "まだ許可されたチャンネルがないよ。まず `/oracle allow` で教えてね！っ",
                ephemeral=True,
            )
            return
        job_id = await self.store.enqueue_sync(guild_id, str(interaction.user.id))
        msg = (
            "🔄 差分取り込みを予約したよ！っ"
            if job_id is not None
            else "取り込みはもう予約済みだよ。順番に処理するから待っててね！っ"
        )
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="status", description="取り込み状況を表示する")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        st = await self.store.status(str(interaction.guild_id))

        channels = ", ".join(f"#{name}" for _, name in st["allowed"]) or "（なし）"
        lines = [
            f"**許可チャンネル**: {len(st['allowed'])} 件 — {channels}",
            f"**取り込み済みメッセージ**: {st['messages']:,} 件",
            f"**チャンク**: {st['chunks']:,} 件（インデックス済み {st['indexed']:,} 件）",
        ]
        job = st["last_job"]
        if job:
            label = _JOB_STATUS_LABEL.get(job["status"], job["status"])
            detail = job["result"] or job["error_message"] or ""
            lines.append(f"**最新ジョブ**: {job['kind']} — {label} {detail}")
        else:
            lines.append("**最新ジョブ**: なし（`/oracle allow` で取り込みを始めてね）")
        await interaction.followup.send("\n".join(lines), ephemeral=True)


class MoimoichanBot(discord.Client):
    def __init__(self, oracle: OracleClient, store: Store, cfg: dict) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.oracle = oracle
        self.store = store
        self.cfg = cfg
        self.tree = app_commands.CommandTree(self)
        # チャンネルごとの直近会話履歴（マルチターン・OI-10）。
        # 1チャンネル＝1つの会話として扱う（グループチャットの自然な単位）。
        # 各要素は {"role": "user"|"assistant", "content": str}。
        self._history_max_turns = int(
            cfg.get("oracle", {}).get(
                "history_max_turns", _DEFAULT_HISTORY_MAX_TURNS
            )
        )
        self._history: dict[int, deque] = {}

    async def setup_hook(self) -> None:
        self.tree.add_command(OracleGroup(self.store))
        await self.tree.sync()

    async def on_ready(self) -> None:
        print(f"[INFO] Logged in as {self.user} (id={self.user.id})")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        print(f"[INFO] サーバー参加: {guild.name} (id={guild.id})")
        await self.store.register_guild(str(guild.id), guild.name)
        channel = guild.system_channel
        if channel is not None:
            try:
                await channel.send(_WELCOME)
            except discord.Forbidden:
                pass  # 挨拶が送れなくても opt-in 運用には支障なし

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        print(f"[INFO] サーバー退出: {guild.name} (id={guild.id}) → データ削除を予約")
        await self.store.guild_left(str(guild.id))

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
        history = self._get_history(message.channel.id)

        async with message.channel.typing():
            try:
                answer = await self.oracle.chat(
                    query, str(message.guild.id), user,
                    guild_name=message.guild.name,
                    history=history,
                )
                # 成功時のみ会話を記憶（このチャンネルの次ターンへ引き継ぐ）。
                self._remember_turn(message.channel.id, query, answer)
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

    def _get_history(self, channel_id: int) -> list[dict]:
        """このチャンネルの直近会話を古い順で返す（API へ渡す形）。"""
        buf = self._history.get(channel_id)
        return list(buf) if buf else []

    def _remember_turn(self, channel_id: int, query: str, answer: str) -> None:
        """1ターン（ユーザー質問＋Bot回答）を履歴に追記する。
        maxlen で直近 history_max_turns ペアだけ保持する。"""
        if self._history_max_turns <= 0:
            return
        buf = self._history.get(channel_id)
        if buf is None:
            buf = deque(maxlen=self._history_max_turns * 2)
            self._history[channel_id] = buf
        buf.append({"role": "user", "content": query})
        buf.append({"role": "assistant", "content": answer})

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
    store = Store()
    bot = MoimoichanBot(oracle=oracle, store=store, cfg=cfg)
    bot.run(token)


if __name__ == "__main__":
    main()
