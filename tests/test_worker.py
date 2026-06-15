"""src/worker.py のテスト（DBは実Postgres・Discord/パイプライン/Qdrantはフェイク）"""

from __future__ import annotations

import asyncio

from src.db import (
    JOB_INGEST,
    JOB_PURGE_CHANNEL,
    JOB_PURGE_GUILD,
    allow_channel,
    claim_next_job,
    count_chunks,
    count_messages,
    enqueue_job,
    fetch_last_job,
    insert_chunk,
    insert_message,
    upsert_guild,
)
from src.models import RawMessage
from src.worker import IngestWorker


class FakeStore:
    """Qdrant を呼ばず削除要求だけ記録する。"""

    def __init__(self) -> None:
        self.deleted_channels: list[tuple[str, str]] = []
        self.deleted_guilds: list[str] = []

    def delete_by_channel(self, guild_id: str, channel_id: str) -> None:
        self.deleted_channels.append((guild_id, channel_id))

    def delete_by_guild(self, guild_id: str) -> None:
        self.deleted_guilds.append(guild_id)


def _make_worker(conn, store=None) -> IngestWorker:
    return IngestWorker(
        conn, cfg={}, store=store or FakeStore(), embedder=None, token="fake-token"
    )


def _insert_message(conn, msg_id: str, guild_id: str, channel_id: str) -> None:
    insert_message(conn, RawMessage(
        id=msg_id, guild_id=guild_id, channel_id=channel_id, channel_name="general",
        author_id="u1", author_name="user", content="本文",
        timestamp="2024-01-01T00:00:00+00:00", has_attachment=False,
        is_pinned=False, reaction_count=0, thread_id=None, thread_name=None,
    ))


def _patch_pipeline(monkeypatch, worker, crawled=5, chunks=3, contexts=2, indexed=3):
    async def fake_crawl(guild_id, run_id):
        return crawled

    monkeypatch.setattr(worker, "_crawl", fake_crawl)
    monkeypatch.setattr(
        "src.worker.run_chunker", lambda conn, cfg, run_id, guild_id: chunks
    )
    monkeypatch.setattr(
        "src.worker.run_contextualizer", lambda conn, cfg, guild_id: contexts
    )
    monkeypatch.setattr(
        "src.worker.run_indexer",
        lambda conn, cfg, store, embedder, guild_id: indexed,
    )


class TestRunOnce:
    def test_empty_queue_returns_false(self, conn):
        assert asyncio.run(_make_worker(conn).run_once()) is False

    def test_ingest_job_success(self, conn, monkeypatch):
        enqueue_job(conn, "g1", JOB_INGEST)
        worker = _make_worker(conn)
        _patch_pipeline(monkeypatch, worker)

        assert asyncio.run(worker.run_once()) is True

        job = fetch_last_job(conn, "g1")
        assert job["status"] == "done"
        assert job["result"] == "crawled=5 chunks=3 contexts=2 indexed=3"

    def test_failed_job_records_error_and_keeps_connection_usable(self, conn, monkeypatch):
        enqueue_job(conn, "g1", JOB_INGEST)
        worker = _make_worker(conn)
        _patch_pipeline(monkeypatch, worker)

        def boom(conn_, cfg, run_id, guild_id):
            raise RuntimeError("チャンク化失敗")

        monkeypatch.setattr("src.worker.run_chunker", boom)

        assert asyncio.run(worker.run_once()) is True

        job = fetch_last_job(conn, "g1")
        assert job["status"] == "error"
        assert "チャンク化失敗" in job["error_message"]
        # rollback 済みで接続は引き続き使える
        assert claim_next_job(conn) is None

    def test_unknown_kind_results_in_error(self, conn):
        enqueue_job(conn, "g1", "bogus_kind")
        worker = _make_worker(conn)

        asyncio.run(worker.run_once())

        job = fetch_last_job(conn, "g1")
        assert job["status"] == "error"


class TestPurgeJobs:
    def test_purge_channel_job(self, conn):
        _insert_message(conn, "m1", "g1", "ch1")
        _insert_message(conn, "m2", "g1", "ch2")
        insert_chunk(conn, "c1", "g1", "m1", "ch1", "本文")
        conn.commit()
        enqueue_job(conn, "g1", JOB_PURGE_CHANNEL, channel_id="ch1")

        store = FakeStore()
        asyncio.run(_make_worker(conn, store).run_once())

        assert store.deleted_channels == [("g1", "ch1")]
        assert count_messages(conn, guild_id="g1") == 1  # ch2 のみ残る
        assert count_chunks(conn, guild_id="g1") == 0
        assert fetch_last_job(conn, "g1")["status"] == "done"

    def test_purge_guild_job(self, conn):
        _insert_message(conn, "m1", "g1", "ch1")
        _insert_message(conn, "m2", "g2", "ch9")
        conn.commit()
        enqueue_job(conn, "g1", JOB_PURGE_GUILD)

        store = FakeStore()
        asyncio.run(_make_worker(conn, store).run_once())

        assert store.deleted_guilds == ["g1"]
        assert count_messages(conn, guild_id="g1") == 0
        assert count_messages(conn, guild_id="g2") == 1  # 他guildは無傷


class TestScheduleSyncs:
    def test_enqueues_for_due_guild(self, conn):
        upsert_guild(conn, "g1", "server")
        allow_channel(conn, "g1", "ch1", "general", "admin")

        worker = _make_worker(conn)
        worker.schedule_syncs()

        job = claim_next_job(conn)
        assert job is not None
        assert job["guild_id"] == "g1"
        assert job["kind"] == JOB_INGEST
        assert job["requested_by"] == "scheduler"

    def test_no_duplicate_when_job_already_queued(self, conn):
        upsert_guild(conn, "g1", "server")
        allow_channel(conn, "g1", "ch1", "general", "admin")
        enqueue_job(conn, "g1", JOB_INGEST)

        worker = _make_worker(conn)
        worker.schedule_syncs()

        claim_next_job(conn)
        assert claim_next_job(conn) is None  # 2件目は積まれていない

    def test_guild_without_allowed_channels_not_scheduled(self, conn):
        upsert_guild(conn, "g1", "server")  # allow なし

        worker = _make_worker(conn)
        worker.schedule_syncs()

        assert claim_next_job(conn) is None
