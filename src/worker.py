"""取り込みワーカー: ingest_jobs キューを監視してパイプラインを自動実行する。worker.py から使用。

ジョブ種別:
- ingest:        クロール → チャンク化 → 文脈付与 → Qdrant登録（差分・冪等）
- purge_channel: 1チャンネル分のデータを Qdrant / Postgres から削除
- purge_guild:   1サーバー分のデータを Qdrant / Postgres から削除

ジョブが無いあいだは定期syncのスケジューラとして動き、
最後の取り込みから sync_interval_hours 経過したサーバーに ingest ジョブを投入する。
"""

from __future__ import annotations

import asyncio
import traceback
import uuid

import discord
import psycopg

from src.chunker import run_chunker
from src.collectors.text_channel import TextChannelCollector
from src.contextualizer import run_contextualizer
from src.db import (
    JOB_INGEST,
    JOB_PURGE_CHANNEL,
    JOB_PURGE_GUILD,
    claim_next_job,
    enqueue_job,
    fetch_allowed_channels,
    finish_job,
    guilds_due_for_sync,
    purge_channel_data,
    purge_guild_data,
    upsert_guild,
)
from src.embedder import Embedder
from src.indexer import run_indexer
from src.sparse import SparseEncoder
from src.vectorstore import VectorStore


class IngestWorker:
    def __init__(
        self,
        conn: psycopg.Connection,
        cfg: dict,
        store: VectorStore,
        embedder: Embedder,
        token: str,
        poll_interval: float = 10.0,
        sync_interval_hours: float = 24.0,
        sparse_encoder: SparseEncoder | None = None,
    ) -> None:
        self._conn = conn
        self._cfg = cfg
        self._store = store
        self._embedder = embedder
        self._token = token
        self._poll_interval = poll_interval
        self._sync_interval_hours = sync_interval_hours
        # ハイブリッド検索（#54）。あれば取り込み時に BM25 sparse も生成・格納する。
        self._sparse_encoder = sparse_encoder

    async def run_forever(self) -> None:
        print(
            f"ワーカー起動: poll={self._poll_interval}s "
            f"sync_interval={self._sync_interval_hours}h"
        )
        while True:
            processed = await self.run_once()
            if not processed:
                self.schedule_syncs()
                await asyncio.sleep(self._poll_interval)

    async def run_once(self) -> bool:
        """キューの先頭ジョブを1件処理する。処理したら True、キューが空なら False。"""
        job = claim_next_job(self._conn)
        if job is None:
            return False

        print(f"[job {job['id']}] {job['kind']} guild={job['guild_id']} 開始")
        try:
            result = await self._dispatch(job)
            finish_job(self._conn, job["id"], True, result=result)
            print(f"[job {job['id']}] 完了: {result}")
        except Exception as e:
            # 失敗したトランザクションを破棄しないと finish_job 自体が失敗する
            self._conn.rollback()
            finish_job(
                self._conn, job["id"], False,
                error_message=f"{type(e).__name__}: {e}",
            )
            print(f"[job {job['id']}] エラー: {type(e).__name__}: {e}")
            traceback.print_exc()
        return True

    def schedule_syncs(self) -> None:
        """定期syncが必要なサーバーに ingest ジョブを投入する。"""
        for guild_id in guilds_due_for_sync(self._conn, self._sync_interval_hours):
            job_id = enqueue_job(
                self._conn, guild_id, JOB_INGEST, requested_by="scheduler"
            )
            if job_id is not None:
                print(f"[scheduler] guild={guild_id} の定期syncを投入 (job {job_id})")

    # ---- ジョブ処理 ----

    async def _dispatch(self, job: dict) -> str:
        kind = job["kind"]
        if kind == JOB_INGEST:
            return await self._ingest(job["guild_id"])
        if kind == JOB_PURGE_CHANNEL:
            return self._purge_channel(job["guild_id"], job["channel_id"])
        if kind == JOB_PURGE_GUILD:
            return self._purge_guild(job["guild_id"])
        raise ValueError(f"不明なジョブ種別: {kind}")

    async def _ingest(self, guild_id: str) -> str:
        run_id = str(uuid.uuid4())

        crawled = await self._crawl(guild_id, run_id)

        # 以下はブロッキング処理なので別スレッドで実行する
        # （run_contextualizer は内部で asyncio.run するためイベントループ上では呼べない）
        chunks = await asyncio.to_thread(
            run_chunker, self._conn, self._cfg, run_id, guild_id
        )
        self._conn.commit()
        contexts = await asyncio.to_thread(
            run_contextualizer, self._conn, self._cfg, guild_id
        )
        self._conn.commit()
        indexed = await asyncio.to_thread(
            run_indexer,
            self._conn,
            self._cfg,
            self._store,
            self._embedder,
            guild_id,
            False,
            self._sparse_encoder,
        )
        self._conn.commit()

        return (
            f"crawled={crawled} chunks={chunks} "
            f"contexts={contexts} indexed={indexed}"
        )

    async def _crawl(self, guild_id: str, run_id: str) -> int:
        """許可チャンネルだけを REST API で差分クロールする（gateway接続なし）。"""
        allowed = fetch_allowed_channels(self._conn, guild_id)
        if not allowed:
            return 0
        allowed_ids = {channel_id for channel_id, _ in allowed}

        client = discord.Client(intents=discord.Intents.none())
        await client.login(self._token)
        try:
            guild = await client.fetch_guild(int(guild_id))
            upsert_guild(self._conn, guild_id, guild.name)

            channels = await guild.fetch_channels()
            targets = [
                ch for ch in channels
                if isinstance(ch, discord.TextChannel) and str(ch.id) in allowed_ids
            ]
            collector = TextChannelCollector(guild, self._cfg)
            total = await collector.collect(self._conn, run_id, channels=targets)
            self._conn.commit()
            return total
        finally:
            await client.close()

    def _purge_channel(self, guild_id: str, channel_id: str) -> str:
        self._store.delete_by_channel(guild_id, channel_id)
        stats = purge_channel_data(self._conn, guild_id, channel_id)
        return f"messages={stats['messages']} chunks={stats['chunks']} 削除"

    def _purge_guild(self, guild_id: str) -> str:
        self._store.delete_by_guild(guild_id)
        stats = purge_guild_data(self._conn, guild_id)
        return f"messages={stats['messages']} chunks={stats['chunks']} 削除"
