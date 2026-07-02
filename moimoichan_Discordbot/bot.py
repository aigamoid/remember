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
    /oracle allowall         全チャンネルの読み取りを一括許可（MAXプラン限定・OI-25）
    /oracle deny <channel>   許可を取り消し、取り込み済みデータを削除
    /oracle sync             許可チャンネルの差分取り込みを今すぐ実行
    /oracle status           取り込み状況を表示
    /oracle upgrade [plan]   有料プランに申し込む（Stripe Checkout・OI-14 D）
    /oracle billing          プラン変更・解約（Stripe Customer Portal・OI-14 D）
    /oracle help             使い方とコマンド一覧を表示（オンボーディング・OI-27）

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
# 「覚えておいて」検知のデフォルトフレーズ（部分一致・OI-24 書き込み）。
# メンション必須（mention_only）と併用するので、これらを含むメンション発話だけ記憶フローに入る。
_DEFAULT_REMEMBER_PHRASES = [
    "覚えておいて", "覚えといて", "覚えてて", "覚えといて",
    "おぼえておいて", "おぼえといて", "記憶して", "メモして",
]

_JOB_STATUS_LABEL = {
    "queued": "⏳ 待機中",
    "running": "🏃 実行中",
    "done": "✅ 完了",
    "error": "⚠️ エラー",
}

_WELCOME = (
    "はじめまして、れみちゃんだよ〜 🌸\n"
    "このサーバーの過去ログをぼんやり覚えて、質問に答えられるようになるかも。\n"
    "**許可されたチャンネルしか読まない**から、安心してね。\n"
    "サーバー管理権限を持つ人が `/oracle allow #チャンネル` で読んでいい"
    "チャンネルを教えてくれたら、取り込みを始めるね〜"
)

# /oracle help の本文（オンボーディング・OI-27）。ハードコードでよい
# （コマンド一覧は頻繁に変わらないため）。コマンドを増減したらここも更新する。
_HELP = (
    "**れみちゃんの使い方** 🌸\n"
    "このサーバーの過去ログを覚えて、メンションで質問すると答えるBotだよ。\n"
    "\n"
    "**導入の流れ（3ステップ）**\n"
    "1️⃣ `/oracle allow #チャンネル` で読んでいいチャンネルを許可する"
    "（全部まとめてなら `/oracle allowall`）\n"
    "2️⃣ `/oracle sync` で過去ログを取り込む（初回は自動でも始まるよ）\n"
    "3️⃣ 取り込みが終わったら、れみちゃんに **メンションして質問** してね〜\n"
    "\n"
    "**コマンド一覧**（サーバー管理権限が必要）\n"
    "・`/oracle allow #チャンネル` … そのチャンネルの読み取りを許可して取り込み開始\n"
    "・`/oracle allowall` … 全チャンネルを一括で許可（MAXプラン限定）\n"
    "・`/oracle deny #チャンネル` … 許可を取り消して取り込み済みデータを削除\n"
    "・`/oracle sync` … 許可チャンネルの新着を今すぐ取り込む\n"
    "・`/oracle status` … 取り込み状況（許可数・件数・最新ジョブ）を表示\n"
    "・`/oracle upgrade` … 有料プランに申し込む（決済ページを開くよ）\n"
    "・`/oracle billing` … プラン変更・解約・カード変更（管理ページを開くよ）\n"
    "・`/oracle help` … この使い方を表示\n"
    "\n"
    "**🪄 真似っこモード**\n"
    "メンバーの過去の発言から口調・性格をプロファイリングして、れみがその人っぽく話すよ。\n"
    "・`/oracle mimic @メンバー` … その人の真似を始める（**このチャンネルだけ**で効くよ）\n"
    "・`/oracle mimic_off` … 真似っこを解除して元のれみに戻る\n"
    "・`/mimic_optout` … 自分を真似の対象から外す（**本人なら誰でも**実行できるよ）\n"
    "※あくまで れみ によるモノマネ遊びだよ。サーバーで有効化されているときだけ使えるよ。\n"
    "\n"
    "**ちょっと便利**\n"
    "・「◯◯は△△だよ、覚えておいて」とメンションで言うと、その場で覚えるよ📝\n"
    "・取り込み状況やコスト・利用量は管理ポータル **remember** からも確認できるよ。\n"
    "\n"
    "**読むのは許可されたチャンネルだけ**だから、安心して使ってね〜 🌸"
)

# 公開/課金前の明示同意（#41 / OI-48・法務）。初回の許可操作（/oracle allow|allowall）時に
# 下記文面を提示し、同意ボタン押下で consent_log に記録する。規約内容を変えたらこの版を上げる
# （上げると全サーバーが次回の許可操作時に再同意を求められる）。
CONSENT_TERMS_VERSION = "v1-2026-06-30"

_CONSENT_TEXT = (
    "**取り込みを始める前に、確認とお願い** 🌸\n"
    "れみちゃんを使うと、許可したチャンネルについて次のことが起きるよ。管理者として同意してね。\n"
    "\n"
    "1️⃣ 許可チャンネルの**過去ログ本文を保存**して、質問に答えるために使うよ（RAG）。\n"
    "2️⃣ 回答や前処理のために、メッセージ内容を**外部のLLM API（OpenAI・OpenRouter）へ送信**するよ。\n"
    "3️⃣ **料金・1日の質問上限（quota）・削除ポリシー**があるよ。"
    "取り込んだデータは `/oracle deny #チャンネル` で削除でき、れみがサーバーを抜けると全部消えるよ。\n"
    "\n"
    "内容に同意できたら下のボタンを押してね。**同意した管理者・日時・対象チャンネルを記録**するよ。"
)

_CONSENT_TEXT_ALL = (
    "**⚠️ 全チャンネル一括許可の確認** 🌸\n"
    "`/oracle allowall` は、れみが読める**サーバーの全テキストチャンネル**を一気に取り込み対象にするよ。"
    "対象が広いから、特にしっかり確認してね。\n"
    "\n"
    "1️⃣ 全許可チャンネルの**過去ログ本文を保存**して、質問に答えるために使うよ（RAG）。\n"
    "2️⃣ 回答や前処理のために、メッセージ内容を**外部のLLM API（OpenAI・OpenRouter）へ送信**するよ。\n"
    "3️⃣ **料金・1日の質問上限（quota）・削除ポリシー**があるよ。"
    "取り込んだデータは `/oracle deny #チャンネル` で個別に、れみがサーバーを抜けると全部削除されるよ。\n"
    "\n"
    "**全チャンネルが対象になること**に同意できたら、下のボタンを押してね。"
    "**同意した管理者・日時・対象チャンネル一覧を記録**するよ。"
)


class ConsentView(discord.ui.View):
    """初回の許可操作時に同意を取るボタンUI（#41 / OI-48）。

    同意ボタン押下で consent_log に記録してから、本来の許可処理（on_agree）を実行する。
    押せるのは操作を始めた管理者本人だけ（interaction_check）。
    """

    def __init__(
        self,
        *,
        store: "Store",
        guild_id: str,
        admin_id: str,
        scope: str,
        channels: list[dict],
        on_agree,
    ) -> None:
        super().__init__(timeout=180)  # 3分で無効化
        self.store = store
        self.guild_id = guild_id
        self.admin_id = admin_id
        self.scope = scope            # 'allow' | 'allowall'
        self.channels = channels      # 監査用の対象ch控え [{"id","name"}, ...]
        self.on_agree = on_agree      # async (interaction) -> None : 実際の許可処理

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.admin_id:
            await interaction.response.send_message(
                "この同意ボタンは、操作を始めた本人だけが押せるよ〜", ephemeral=True
            )
            return False
        return True

    def _disable_all(self) -> None:
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="✅ 同意して許可する", style=discord.ButtonStyle.success)
    async def agree(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._disable_all()
        await self.store.record_consent(
            self.guild_id, self.admin_id, CONSENT_TERMS_VERSION, self.scope, self.channels
        )
        await interaction.response.edit_message(
            content="🌸 同意ありがとう！手続きを進めるね〜", view=self
        )
        await self.on_agree(interaction)
        self.stop()

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._disable_all()
        await interaction.response.edit_message(
            content="またいつでもどうぞ〜。今回は許可してないよ。", view=self
        )
        self.stop()


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

    def __init__(self, store: Store, oracle: OracleClient | None = None) -> None:
        super().__init__(
            name="oracle",
            description="過去ログ取り込みの管理（サーバー管理権限が必要）",
            default_permissions=discord.Permissions(manage_guild=True),
            guild_only=True,
        )
        self.store = store
        self.oracle = oracle  # 真似っこ（#49）で API を呼ぶため

    @app_commands.command(name="allow", description="チャンネルの読み取りを許可して取り込みを開始する")
    @app_commands.describe(channel="読み取りを許可するテキストチャンネル")
    async def allow(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        await self.store.register_guild(guild_id, interaction.guild.name)
        # 初回は同意を取る（#41 / OI-48）。同意済みサーバーはそのまま許可処理へ。
        if not await self.store.has_consented(guild_id, CONSENT_TERMS_VERSION):
            view = ConsentView(
                store=self.store,
                guild_id=guild_id,
                admin_id=str(interaction.user.id),
                scope="allow",
                channels=[{"id": str(channel.id), "name": channel.name}],
                on_agree=lambda i: self._do_allow(i, channel),
            )
            await interaction.followup.send(_CONSENT_TEXT, view=view, ephemeral=True)
            return
        await self._do_allow(interaction, channel)

    async def _do_allow(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        """チャンネル許可の本処理（同意済み前提）。コマンド本体 or 同意ボタンから呼ばれる。
        どちらの経路でも interaction の応答は済んでいるので followup.send を使う。"""
        guild_id = str(interaction.guild_id)
        result = await self.store.allow_channel(
            guild_id, str(channel.id), channel.name, str(interaction.user.id)
        )
        if not result["ok"]:  # プランのチャンネル数上限に達した
            await interaction.followup.send(
                f"⚠️ {result['message']}", ephemeral=True
            )
            return
        job_id = result["job_id"]  # None=取り込みジョブが重複（既にキュー済み）
        note = (
            "取り込みを始めるね。終わったら質問できるよ〜。"
            if job_id is not None
            else "取り込みはもう予約済みだから、そのまま待っててね〜。"
        )
        await interaction.followup.send(
            f"✅ {channel.mention} の読み取りを許可したよ。{note}", ephemeral=True
        )

    @app_commands.command(
        name="allowall",
        description="全チャンネルの読み取りを一括で許可して取り込む（MAXプラン限定）",
    )
    async def allowall(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        guild_id = str(guild.id)
        await self.store.register_guild(guild_id, guild.name)

        # Botが閲覧＋履歴読み取りできるテキストチャンネルだけを対象にする
        # （権限の無いチャンネルを許可してもクロールできないため）。
        me = guild.me
        channels = [
            (str(ch.id), ch.name)
            for ch in guild.text_channels
            if (perms := ch.permissions_for(me)).view_channel
            and perms.read_message_history
        ]
        if not channels:
            await interaction.followup.send(
                "読み取れるテキストチャンネルが見つからなかったよ〜。"
                "Botにチャンネルの閲覧・履歴の読み取り権限があるか確認してね。",
                ephemeral=True,
            )
            return

        # 初回は同意を取る（#41 / OI-48）。allowall は全ch対象なので強い文面で確認する。
        if not await self.store.has_consented(guild_id, CONSENT_TERMS_VERSION):
            view = ConsentView(
                store=self.store,
                guild_id=guild_id,
                admin_id=str(interaction.user.id),
                scope="allowall",
                channels=[{"id": cid, "name": name} for cid, name in channels],
                on_agree=lambda i: self._do_allowall(i, channels),
            )
            await interaction.followup.send(_CONSENT_TEXT_ALL, view=view, ephemeral=True)
            return
        await self._do_allowall(interaction, channels)

    async def _do_allowall(
        self, interaction: discord.Interaction, channels: list[tuple[str, str]]
    ) -> None:
        """全チャンネル一括許可の本処理（同意済み前提）。コマンド本体 or 同意ボタンから呼ばれる。
        channels は権限フィルタ済みの [(channel_id, channel_name), ...]。"""
        guild_id = str(interaction.guild_id)
        result = await self.store.allow_all_channels(
            guild_id, channels, str(interaction.user.id)
        )
        if not result["ok"]:  # MAX以外のプラン
            await interaction.followup.send(
                f"⚠️ {result['message']}", ephemeral=True
            )
            return

        added, total = result["added"], result["total"]
        if added == 0:
            await interaction.followup.send(
                f"全 {total} チャンネルはもう許可済みだったよ。新しく追加したものはなし〜。"
                " 取り込み直したいときは `/oracle sync` してね。",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"✅ 全 {total} チャンネルのうち {added} チャンネルを新しく許可したよ。"
            " 順番に取り込むから、終わったら質問できるよ〜。",
            ephemeral=True,
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
            f"{head} 取り込み済みデータの削除も予約したからね〜。", ephemeral=True
        )

    @app_commands.command(name="sync", description="許可チャンネルの新着メッセージを今すぐ取り込む")
    async def sync(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        status = await self.store.status(guild_id)
        if not status["allowed"]:
            await interaction.followup.send(
                "まだ許可されたチャンネルがないよ。まず `/oracle allow` で教えてね〜。",
                ephemeral=True,
            )
            return
        job_id = await self.store.enqueue_sync(guild_id, str(interaction.user.id))
        msg = (
            "🔄 差分取り込みを予約したよ〜。"
            if job_id is not None
            else "取り込みはもう予約済みだよ。順番に処理するから待っててね〜。"
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

    @app_commands.command(name="help", description="れみちゃんの使い方とコマンド一覧を表示する")
    async def help(self, interaction: discord.Interaction) -> None:
        # 静的なヘルプを返すだけなので DB アクセスも defer も不要（OI-27）。
        await interaction.response.send_message(_HELP, ephemeral=True)

    @app_commands.command(
        name="upgrade",
        description="有料プランに申し込む（Stripeの決済ページを開くよ・OI-14 D）",
    )
    @app_commands.describe(plan="申し込むプラン（省略すると一覧を出すよ）")
    async def upgrade(
        self, interaction: discord.Interaction, plan: str | None = None
    ) -> None:
        # 課金導線は本人にだけ見せる（ephemeral）。OracleGroup の manage_guild を継承。
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id is None:  # guild_only だが念のため明示拒否
            await interaction.followup.send(
                "このコマンドはサーバー内で使ってね〜", ephemeral=True
            )
            return
        if self.oracle is None:
            await interaction.followup.send(
                "いま課金機能は使えないみたい〜", ephemeral=True
            )
            return
        guild_id = str(interaction.guild_id)

        # プラン未指定 → 有料プランの一覧を案内して終わり。
        if not plan:
            try:
                plans = await self.store.fetch_plans()
            except Exception:
                plans = []
            paid = [p for p in plans if (p.get("price_jpy") or 0) > 0]
            if not paid:
                await interaction.followup.send(
                    "いま申し込める有料プランが見つからないみたい〜", ephemeral=True
                )
                return
            lines = ["**申し込めるプラン** 🌸", ""]
            for p in paid:
                cl = p["channel_limit"]
                ch = "全チャンネル" if cl is None else f"{cl}チャンネル"
                lines.append(
                    f"・`{p['plan_key']}` … **{p['display_name']}**"
                    f"（¥{p['price_jpy']}/月・{ch}・{p['daily_question_limit']}問/日）"
                )
            lines.append("")
            lines.append("`/oracle upgrade plan:プラン名` で申し込めるよ〜")
            await interaction.followup.send("\n".join(lines), ephemeral=True)
            return

        # プラン指定あり → Checkout URL を発行。
        try:
            status, body = await self.oracle.create_checkout(guild_id, plan)
        except Exception:
            await interaction.followup.send(
                "決済ページの準備に失敗しちゃった…少し待ってからまた試してね〜",
                ephemeral=True,
            )
            return
        if status == 200 and body.get("url"):
            await interaction.followup.send(
                f"こちらから申し込めるよ〜 🌸\n{body['url']}\n"
                "（決済が終わると自動でプランが切り替わるよ）",
                ephemeral=True,
            )
        elif status == 409:
            await interaction.followup.send(
                "このサーバーはもう契約中みたい。プラン変更や解約は "
                "`/oracle billing` からできるよ〜",
                ephemeral=True,
            )
        elif status == 400:
            await interaction.followup.send(
                f"`{plan}` ってプランは見つからなかったよ。"
                "`/oracle upgrade`（プラン名なし）で一覧を見てね〜",
                ephemeral=True,
            )
        elif status == 503:
            await interaction.followup.send(
                "いま課金の準備中みたい。もう少し待ってね〜", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "決済ページの準備に失敗しちゃった…少し待ってからまた試してね〜",
                ephemeral=True,
            )

    @app_commands.command(
        name="billing",
        description="プラン変更・解約・カード変更（Stripeの管理ページを開くよ・OI-14 D）",
    )
    async def billing(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id is None:
            await interaction.followup.send(
                "このコマンドはサーバー内で使ってね〜", ephemeral=True
            )
            return
        if self.oracle is None:
            await interaction.followup.send(
                "いま課金機能は使えないみたい〜", ephemeral=True
            )
            return
        guild_id = str(interaction.guild_id)
        try:
            status, body = await self.oracle.billing_portal(guild_id)
        except Exception:
            await interaction.followup.send(
                "管理ページの準備に失敗しちゃった…少し待ってからまた試してね〜",
                ephemeral=True,
            )
            return
        if status == 200 and body.get("url"):
            await interaction.followup.send(
                f"プラン変更・解約はこちらからどうぞ〜 🌸\n{body['url']}",
                ephemeral=True,
            )
        elif status == 404:
            await interaction.followup.send(
                "まだ有料プランの契約がないみたい。"
                "`/oracle upgrade` から申し込めるよ〜",
                ephemeral=True,
            )
        elif status == 503:
            await interaction.followup.send(
                "いま課金の準備中みたい。もう少し待ってね〜", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "管理ページの準備に失敗しちゃった…少し待ってからまた試してね〜",
                ephemeral=True,
            )

    @app_commands.command(
        name="mimic",
        description="指定したメンバーの口調・性格を真似して話す（#49）",
    )
    @app_commands.describe(member="真似してほしいメンバー")
    async def mimic(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await interaction.response.defer()  # 宣言はみんなに見せたいので非 ephemeral
        if self.oracle is None:
            await interaction.followup.send("いま真似っこ機能は使えないみたい〜")
            return
        guild_id = str(interaction.guild_id)
        try:
            result = await self.oracle.mimic_start(
                guild_id, str(member.id), str(interaction.channel_id),
                target_name=member.display_name,
                user=f"{interaction.channel_id}:{interaction.user.id}",
            )
        except Exception as e:
            print(f"[ERROR] mimic_start: {type(e).__name__}: {e}")
            await interaction.followup.send("⚠️ 真似の準備に失敗しちゃった。あとでもう一度試してね〜")
            return
        if not result.get("started"):
            await interaction.followup.send(
                result.get("reason") or "うまく真似できなかったかも〜"
            )
            return
        await interaction.followup.send(result.get("declaration") or "真似はじめるね！")

    @app_commands.command(
        name="mimic_off", description="真似っこモードを解除して元のれみに戻る（#49）"
    )
    async def mimic_off(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if self.oracle is None:
            await interaction.followup.send("いま真似っこ機能は使えないみたい〜")
            return
        try:
            result = await self.oracle.mimic_stop(
                str(interaction.guild_id), str(interaction.channel_id)
            )
        except Exception as e:
            print(f"[ERROR] mimic_stop: {type(e).__name__}: {e}")
            await interaction.followup.send("⚠️ 解除に失敗しちゃった。もう一度試してね〜")
            return
        if result.get("stopped"):
            await interaction.followup.send("ふぅ、元のれみに戻ったよ〜🪄")
        else:
            await interaction.followup.send("いまこのチャンネルでは誰も真似してないみたい〜")


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
        # 「覚えておいて」検知フレーズ（OI-24・書き込み）。config で上書き可。
        self._remember_phrases = (
            cfg.get("oracle", {}).get("remember_phrases")
            or _DEFAULT_REMEMBER_PHRASES
        )

    async def setup_hook(self) -> None:
        self.tree.add_command(OracleGroup(self.store, self.oracle))
        self._register_mimic_optout()
        await self.tree.sync()

    def _register_mimic_optout(self) -> None:
        """本人 opt-out を一般メンバーも使えるトップレベルコマンドとして登録する（#49・§2）。

        /oracle グループは管理者限定（default_permissions=manage_guild）なので、
        本人が自分を真似対象から外す opt-out はグループ外のトップレベルに置く（誰でも実行可）。
        """
        oracle = self.oracle

        @app_commands.command(
            name="mimic_optout",
            description="自分を「真似っこ」の対象から外す（本人の意思表示・#49）",
        )
        @app_commands.guild_only()
        async def mimic_optout(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            if oracle is None:
                await interaction.followup.send(
                    "いま真似っこ機能は使えないみたい〜", ephemeral=True
                )
                return
            try:
                result = await oracle.mimic_optout(
                    str(interaction.guild_id), str(interaction.user.id),
                    user=f"{interaction.channel_id}:{interaction.user.id}",
                )
            except Exception as e:
                print(f"[ERROR] mimic_optout: {type(e).__name__}: {e}")
                await interaction.followup.send(
                    "⚠️ 設定に失敗しちゃった。もう一度試してね〜", ephemeral=True
                )
                return
            if result.get("ok"):
                await interaction.followup.send(
                    "わかった！これからはあなたの真似はしないようにするね🙏", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "設定できなかったかも…あとでもう一度試してね〜", ephemeral=True
                )

        self.tree.add_command(mimic_optout)

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
            await message.reply("何か聞いてみてね〜 🌸")
            return

        user = f"{message.channel.id}:{message.author.id}"

        # 「覚えておいて」検知（OI-24・書き込み）。記憶フローに入ったら chat はしない。
        if self._is_remember(query):
            await self._handle_remember(message, query, user)
            return

        history = self._get_history(message.channel.id)

        async with message.channel.typing():
            try:
                answer = await self.oracle.chat(
                    query, str(message.guild.id), user,
                    guild_name=message.guild.name,
                    history=history,
                    speaker=message.author.display_name,
                    channel_id=str(message.channel.id),
                )
                # 成功時のみ会話を記憶（このチャンネルの次ターンへ引き継ぐ）。
                # 発話者名も一緒に残し、次ターンで「誰の発言か」を区別できるようにする（#63）。
                self._remember_turn(
                    message.channel.id, query, answer,
                    speaker=message.author.display_name,
                )
                reply = answer[:_MAX_REPLY_LEN]
                await message.reply(reply or "……（うーん、何も思いつかなかったかも〜 😅）")
            except asyncio.TimeoutError:
                print(f"[TIMEOUT] channel={message.channel.id} user={message.author.id}")
                try:
                    await message.reply("⏱️ 応答がタイムアウトしちゃった。もう一度試してみてね〜。")
                except Exception:
                    pass
            except Exception as e:
                print(f"[ERROR] {type(e).__name__}: {e}")
                try:
                    await message.reply("⚠️ エラーが発生しちゃった。もう一度試してみてね〜。")
                except Exception:
                    pass

    # ---- 内部ヘルパー ----

    def _is_remember(self, text: str) -> bool:
        """記憶依頼フレーズ（覚えておいて等）を含むか（OI-24・書き込み）。"""
        return any(p in text for p in self._remember_phrases)

    async def _handle_remember(
        self, message: discord.Message, text: str, user: str
    ) -> None:
        """「覚えておいて」発話を /remember に送り、保存結果を返信する（OI-24）。"""
        async with message.channel.typing():
            try:
                res = await self.oracle.remember(
                    text, str(message.guild.id), user,
                    speaker=message.author.display_name,
                    channel_id=str(message.channel.id),
                )
            except Exception as e:
                print(f"[ERROR] remember {type(e).__name__}: {e}")
                await message.reply("⚠️ うまく覚えられなかったかも。もう一度試してね〜。")
                return
        if res.get("saved"):
            subject, content = res.get("subject"), res.get("content")
            if subject:
                await message.reply(f"覚えたよ！〔{subject}〕{content} だね🌸")
            else:
                await message.reply(f"覚えたよ！「{content}」だね🌸")
        else:
            await message.reply(
                "ん〜、何を覚えればいいか分からなかったかも。"
                "「◯◯は△△だよ、覚えておいて」みたいに教えてくれたら覚えるよ〜！"
            )

    def _get_history(self, channel_id: int) -> list[dict]:
        """このチャンネルの直近会話を古い順で返す（API へ渡す形）。"""
        buf = self._history.get(channel_id)
        return list(buf) if buf else []

    def _remember_turn(
        self, channel_id: int, query: str, answer: str, speaker: str | None = None
    ) -> None:
        """1ターン（ユーザー質問＋Bot回答）を履歴に追記する。
        maxlen で直近 history_max_turns ペアだけ保持する。

        speaker は質問した人の表示名（#63）。履歴はチャンネル単位で共有されるため、
        user 発言に発話者名を添えておき、次ターンで別の人の発言と区別できるようにする
        （API→engine._label_history が "名前: 本文" のラベルに描画する）。"""
        if self._history_max_turns <= 0:
            return
        buf = self._history.get(channel_id)
        if buf is None:
            buf = deque(maxlen=self._history_max_turns * 2)
            self._history[channel_id] = buf
        user_turn = {"role": "user", "content": query}
        if speaker:
            user_turn["speaker"] = speaker
        buf.append(user_turn)
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
    api_token = os.getenv("ORACLE_API_TOKEN") or oracle_cfg.get("api_token")
    timeout = oracle_cfg.get("chat_timeout", 90)
    if not api_url:
        print("エラー: ORACLE_API_URL も config.yml の oracle.api_url も未設定です")
        sys.exit(1)

    oracle = OracleClient(base_url=api_url, timeout=timeout, api_token=api_token)
    store = Store()
    bot = MoimoichanBot(oracle=oracle, store=store, cfg=cfg)
    bot.run(token)


if __name__ == "__main__":
    main()
