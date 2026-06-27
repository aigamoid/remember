"""src/db.py のテスト（実Postgresを使用・tests/conftest.py の conn フィクスチャ）"""

from src.db import (
    JOB_INGEST,
    JOB_PURGE_CHANNEL,
    allow_channel,
    claim_next_job,
    count_chunks,
    count_messages,
    deny_channel,
    enqueue_job,
    fetch_allowed_channels,
    fetch_guilds_overview,
    count_memories,
    delete_memory,
    fetch_last_job,
    fetch_memories,
    fetch_mention_map,
    fetch_recent_jobs,
    fetch_usage_summary,
    finish_job,
    get_crawl_state,
    guilds_due_for_sync,
    insert_attachment,
    insert_chunk,
    insert_memory,
    insert_message,
    insert_trace,
    insert_usage,
    log_run,
    mark_guild_left,
    purge_channel_data,
    purge_guild_data,
    upsert_crawl_state,
    upsert_guild,
)
from src.models import RawAttachment, RawMessage


def _make_message(**kwargs) -> RawMessage:
    defaults = dict(
        id="msg-1",
        guild_id="g-1",
        channel_id="ch-1",
        channel_name="general",
        author_id="user-1",
        author_name="Alice",
        content="テストメッセージ",
        timestamp="2024-01-15T12:00:00+00:00",
        has_attachment=False,
        is_pinned=False,
        reaction_count=0,
        thread_id=None,
        thread_name=None,
    )
    return RawMessage(**{**defaults, **kwargs})


def _make_attachment(**kwargs) -> RawAttachment:
    defaults = dict(
        id="att-1",
        message_id="msg-1",
        url="https://cdn.discordapp.com/attachments/1/2/photo.png",
        filename="photo.png",
        content_type="image/png",
    )
    return RawAttachment(**{**defaults, **kwargs})


# ── テーブル初期化 ─────────────────────────────────────────────

class TestInitSchema:
    def test_all_tables_exist(self, conn):
        tables = {
            row[0] for row in
            conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            ).fetchall()
        }
        assert {
            "guilds", "allowed_channels", "messages", "attachments",
            "crawl_state", "chunk_index", "ingest_jobs", "run_log",
        } <= tables

    def test_index_exists(self, conn):
        indexes = {
            row[0] for row in
            conn.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public'").fetchall()
        }
        assert "idx_messages_channel_timestamp" in indexes
        assert "idx_messages_guild" in indexes


# ── insert_message ────────────────────────────────────────────

class TestInsertMessage:
    def test_saves_message(self, conn):
        insert_message(conn, _make_message())
        row = conn.execute(
            "SELECT id, guild_id, content FROM messages WHERE id = 'msg-1'"
        ).fetchone()
        assert row is not None
        assert row[1] == "g-1"
        assert row[2] == "テストメッセージ"

    def test_is_idempotent(self, conn):
        """同じ ID で2回 INSERT しても件数が増えない"""
        msg = _make_message()
        insert_message(conn, msg)
        insert_message(conn, msg)
        assert count_messages(conn) == 1

    def test_saves_empty_content(self, conn):
        """添付のみメッセージ（content=""）も保存できる"""
        insert_message(conn, _make_message(content="", has_attachment=True))
        row = conn.execute(
            "SELECT content, has_attachment FROM messages WHERE id='msg-1'"
        ).fetchone()
        assert row[0] == ""
        assert row[1] == 1  # True → 1

    def test_count_messages_by_guild(self, conn):
        insert_message(conn, _make_message(id="m1", guild_id="g-1"))
        insert_message(conn, _make_message(id="m2", guild_id="g-2"))
        assert count_messages(conn) == 2
        assert count_messages(conn, guild_id="g-1") == 1


# ── fetch_mention_map（OI-18）─────────────────────────────────

class TestFetchMentionMap:
    def test_maps_author_id_to_name(self, conn):
        insert_message(conn, _make_message(id="m1", author_id="111", author_name="アリス"))
        insert_message(conn, _make_message(id="m2", author_id="222", author_name="ボブ"))
        assert fetch_mention_map(conn) == {"111": "アリス", "222": "ボブ"}

    def test_uses_latest_display_name(self, conn):
        # 同一IDで表示名が変わった場合は timestamp 最大（最新）を採用
        insert_message(conn, _make_message(
            id="m1", author_id="111", author_name="旧名", timestamp="2024-01-01T00:00:00+00:00"))
        insert_message(conn, _make_message(
            id="m2", author_id="111", author_name="新名", timestamp="2024-06-01T00:00:00+00:00"))
        assert fetch_mention_map(conn) == {"111": "新名"}

    def test_scoped_by_guild(self, conn):
        insert_message(conn, _make_message(id="m1", guild_id="g-1", author_id="111", author_name="アリス"))
        insert_message(conn, _make_message(id="m2", guild_id="g-2", author_id="222", author_name="ボブ"))
        assert fetch_mention_map(conn, guild_id="g-1") == {"111": "アリス"}


# ── insert_attachment ─────────────────────────────────────────

class TestInsertAttachment:
    def test_saves_attachment(self, conn):
        insert_message(conn, _make_message())
        insert_attachment(conn, _make_attachment())
        row = conn.execute("SELECT id, filename FROM attachments WHERE id='att-1'").fetchone()
        assert row is not None
        assert row[1] == "photo.png"

    def test_is_idempotent(self, conn):
        insert_message(conn, _make_message())
        att = _make_attachment()
        insert_attachment(conn, att)
        insert_attachment(conn, att)
        count = conn.execute("SELECT count(*) FROM attachments").fetchone()[0]
        assert count == 1


# ── crawl_state ───────────────────────────────────────────────

class TestCrawlState:
    def test_returns_none_for_unknown_channel(self, conn):
        assert get_crawl_state(conn, "ch-unknown") is None

    def test_upsert_creates_entry(self, conn):
        upsert_crawl_state(conn, "g-1", "ch-1", "msg-100")
        assert get_crawl_state(conn, "ch-1") == "msg-100"

    def test_upsert_updates_existing_entry(self, conn):
        upsert_crawl_state(conn, "g-1", "ch-1", "msg-100")
        upsert_crawl_state(conn, "g-1", "ch-1", "msg-200")
        assert get_crawl_state(conn, "ch-1") == "msg-200"

    def test_multiple_channels_are_independent(self, conn):
        upsert_crawl_state(conn, "g-1", "ch-1", "msg-100")
        upsert_crawl_state(conn, "g-1", "ch-2", "msg-999")
        assert get_crawl_state(conn, "ch-1") == "msg-100"
        assert get_crawl_state(conn, "ch-2") == "msg-999"


# ── guilds / allowed_channels ─────────────────────────────────

class TestGuilds:
    def test_upsert_guild_registers(self, conn):
        upsert_guild(conn, "g-1", "テストサーバー")
        row = conn.execute(
            "SELECT guild_name, left_at FROM guilds WHERE guild_id='g-1'"
        ).fetchone()
        assert row[0] == "テストサーバー"
        assert row[1] is None

    def test_rejoin_clears_left_at(self, conn):
        upsert_guild(conn, "g-1", "テストサーバー")
        mark_guild_left(conn, "g-1")
        upsert_guild(conn, "g-1", "テストサーバー")  # 再参加
        row = conn.execute("SELECT left_at FROM guilds WHERE guild_id='g-1'").fetchone()
        assert row[0] is None

    def test_mark_guild_left(self, conn):
        upsert_guild(conn, "g-1", "テストサーバー")
        mark_guild_left(conn, "g-1")
        row = conn.execute("SELECT left_at FROM guilds WHERE guild_id='g-1'").fetchone()
        assert row[0] is not None


class TestAllowedChannels:
    def test_allow_and_fetch(self, conn):
        allow_channel(conn, "g-1", "ch-1", "general", "admin-1")
        assert fetch_allowed_channels(conn, "g-1") == [("ch-1", "general")]

    def test_allow_is_idempotent(self, conn):
        allow_channel(conn, "g-1", "ch-1", "general", "admin-1")
        allow_channel(conn, "g-1", "ch-1", "general", "admin-2")
        assert len(fetch_allowed_channels(conn, "g-1")) == 1

    def test_deny_removes(self, conn):
        allow_channel(conn, "g-1", "ch-1", "general", "admin-1")
        assert deny_channel(conn, "g-1", "ch-1") is True
        assert fetch_allowed_channels(conn, "g-1") == []

    def test_deny_unknown_returns_false(self, conn):
        assert deny_channel(conn, "g-1", "ch-unknown") is False

    def test_guilds_are_isolated(self, conn):
        allow_channel(conn, "g-1", "ch-1", "general", "admin-1")
        assert fetch_allowed_channels(conn, "g-2") == []


# ── ingest_jobs ジョブキュー ───────────────────────────────────

class TestJobQueue:
    def test_enqueue_and_claim(self, conn):
        job_id = enqueue_job(conn, "g-1", JOB_INGEST, requested_by="admin-1")
        assert job_id is not None

        job = claim_next_job(conn)
        assert job["id"] == job_id
        assert job["guild_id"] == "g-1"
        assert job["kind"] == JOB_INGEST

    def test_claim_empty_queue_returns_none(self, conn):
        assert claim_next_job(conn) is None

    def test_duplicate_queued_job_not_enqueued(self, conn):
        assert enqueue_job(conn, "g-1", JOB_INGEST) is not None
        assert enqueue_job(conn, "g-1", JOB_INGEST) is None  # 重複

    def test_different_guilds_can_queue_same_kind(self, conn):
        assert enqueue_job(conn, "g-1", JOB_INGEST) is not None
        assert enqueue_job(conn, "g-2", JOB_INGEST) is not None

    def test_running_job_allows_new_queued(self, conn):
        """実行中になったら同種ジョブを追加で予約できる（実行後の新着を拾うため）"""
        enqueue_job(conn, "g-1", JOB_INGEST)
        claim_next_job(conn)  # running になる
        assert enqueue_job(conn, "g-1", JOB_INGEST) is not None

    def test_jobs_claimed_in_fifo_order(self, conn):
        first = enqueue_job(conn, "g-1", JOB_INGEST)
        second = enqueue_job(conn, "g-2", JOB_INGEST)
        assert claim_next_job(conn)["id"] == first
        assert claim_next_job(conn)["id"] == second

    def test_finish_job_done(self, conn):
        job_id = enqueue_job(conn, "g-1", JOB_INGEST)
        claim_next_job(conn)
        finish_job(conn, job_id, True, result="crawled=10")
        job = fetch_last_job(conn, "g-1")
        assert job["status"] == "done"
        assert job["result"] == "crawled=10"

    def test_finish_job_error(self, conn):
        job_id = enqueue_job(conn, "g-1", JOB_INGEST)
        claim_next_job(conn)
        finish_job(conn, job_id, False, error_message="boom")
        job = fetch_last_job(conn, "g-1")
        assert job["status"] == "error"
        assert job["error_message"] == "boom"

    def test_fetch_last_job_none(self, conn):
        assert fetch_last_job(conn, "g-1") is None

    def test_purge_channel_dedup_uses_channel_id(self, conn):
        assert enqueue_job(conn, "g-1", JOB_PURGE_CHANNEL, channel_id="ch-1") is not None
        assert enqueue_job(conn, "g-1", JOB_PURGE_CHANNEL, channel_id="ch-1") is None
        assert enqueue_job(conn, "g-1", JOB_PURGE_CHANNEL, channel_id="ch-2") is not None


class TestGuildsDueForSync:
    def _setup_guild(self, conn, guild_id="g-1"):
        upsert_guild(conn, guild_id, "server")
        allow_channel(conn, guild_id, f"{guild_id}-ch", "general", "admin")

    def test_guild_without_completed_ingest_is_due(self, conn):
        self._setup_guild(conn)
        assert guilds_due_for_sync(conn, interval_hours=24) == ["g-1"]

    def test_guild_with_queued_job_not_due(self, conn):
        self._setup_guild(conn)
        enqueue_job(conn, "g-1", JOB_INGEST)
        assert guilds_due_for_sync(conn, interval_hours=24) == []

    def test_guild_with_recent_ingest_not_due(self, conn):
        self._setup_guild(conn)
        job_id = enqueue_job(conn, "g-1", JOB_INGEST)
        claim_next_job(conn)
        finish_job(conn, job_id, True)
        assert guilds_due_for_sync(conn, interval_hours=24) == []

    def test_guild_with_old_ingest_is_due(self, conn):
        self._setup_guild(conn)
        job_id = enqueue_job(conn, "g-1", JOB_INGEST)
        claim_next_job(conn)
        finish_job(conn, job_id, True)
        # interval=0 なら直前の完了でも経過扱いになる
        assert guilds_due_for_sync(conn, interval_hours=0) == ["g-1"]

    def test_left_guild_not_due(self, conn):
        self._setup_guild(conn)
        mark_guild_left(conn, "g-1")
        assert guilds_due_for_sync(conn, interval_hours=0) == []

    def test_guild_without_allowed_channels_not_due(self, conn):
        upsert_guild(conn, "g-1", "server")  # allow なし
        assert guilds_due_for_sync(conn, interval_hours=0) == []


# ── insert_chunk の更新時リセット ──────────────────────────────

class TestInsertChunkReset:
    def test_text_change_resets_context_and_status(self, conn):
        insert_chunk(conn, "c1", "g-1", "m1", "ch-1", "古い本文")
        conn.execute(
            "UPDATE chunk_index SET context_text='文脈', status='indexed' WHERE chunk_id='c1'"
        )
        insert_chunk(conn, "c1", "g-1", "m1", "ch-1", "新しい本文")
        row = conn.execute(
            "SELECT context_text, status FROM chunk_index WHERE chunk_id='c1'"
        ).fetchone()
        assert row[0] is None       # context は再生成対象
        assert row[1] == "pending"  # 再インデックス対象

    def test_same_text_keeps_context_and_status(self, conn):
        insert_chunk(conn, "c1", "g-1", "m1", "ch-1", "同じ本文")
        conn.execute(
            "UPDATE chunk_index SET context_text='文脈', status='indexed' WHERE chunk_id='c1'"
        )
        insert_chunk(conn, "c1", "g-1", "m1", "ch-1", "同じ本文")
        row = conn.execute(
            "SELECT context_text, status FROM chunk_index WHERE chunk_id='c1'"
        ).fetchone()
        assert row[0] == "文脈"
        assert row[1] == "indexed"


# ── purge ─────────────────────────────────────────────────────

class TestPurge:
    def _setup_data(self, conn):
        for gid, cid, mid in [("g-1", "ch-1", "m1"), ("g-1", "ch-2", "m2"), ("g-2", "ch-3", "m3")]:
            insert_message(conn, _make_message(id=mid, guild_id=gid, channel_id=cid))
            insert_attachment(conn, _make_attachment(id=f"att-{mid}", message_id=mid))
            insert_chunk(conn, f"c-{mid}", gid, mid, cid, "本文")
            upsert_crawl_state(conn, gid, cid, mid)
        conn.commit()

    def test_purge_channel_removes_only_that_channel(self, conn):
        self._setup_data(conn)
        stats = purge_channel_data(conn, "g-1", "ch-1")
        assert stats["messages"] == 1
        assert stats["chunks"] == 1
        assert count_messages(conn, guild_id="g-1") == 1  # ch-2 は残る
        assert get_crawl_state(conn, "ch-1") is None
        assert get_crawl_state(conn, "ch-2") == "m2"
        att = conn.execute("SELECT count(*) FROM attachments WHERE id='att-m1'").fetchone()[0]
        assert att == 0

    def test_purge_guild_removes_all_guild_data(self, conn):
        self._setup_data(conn)
        allow_channel(conn, "g-1", "ch-1", "general", "admin")
        stats = purge_guild_data(conn, "g-1")
        assert stats["messages"] == 2
        assert count_messages(conn, guild_id="g-1") == 0
        assert count_messages(conn, guild_id="g-2") == 1  # 他guildは無傷
        assert count_chunks(conn, guild_id="g-2") == 1
        assert fetch_allowed_channels(conn, "g-1") == []

    def _count(self, conn, table, guild_id):
        return conn.execute(
            f"SELECT count(*) FROM {table} WHERE guild_id = %s", (guild_id,)
        ).fetchone()[0]

    def test_purge_guild_removes_privacy_and_ops_data(self, conn):
        """#31 (OI-44): memories/chat_trace/usage_log/guild_plans/run_log/ingest_jobs も削除する。"""
        for gid in ("g-1", "g-2"):
            insert_memory(conn, gid, "秘密の記憶", created_by="user-1")
            insert_trace(conn, gid, "質問", answer="回答", user_id="user-1")
            insert_usage(conn, gid, "answer", model="m", total_tokens=10, user_id="user-1")
            log_run(conn, f"run-{gid}", "ingest", "ok", guild_id=gid)
            enqueue_job(conn, gid, JOB_INGEST, requested_by="test")
            conn.execute(
                "INSERT INTO guild_plans (guild_id, plan_key) VALUES (%s, 'free') "
                "ON CONFLICT (guild_id) DO NOTHING",
                (gid,),
            )
        conn.commit()

        stats = purge_guild_data(conn, "g-1")
        assert stats["memories"] == 1
        assert stats["traces"] == 1
        assert stats["usage"] == 1

        # g-1 のプライバシー・運用系は全て消える
        for table in ("memories", "chat_trace", "usage_log", "guild_plans", "run_log", "ingest_jobs"):
            assert self._count(conn, table, "g-1") == 0, f"{table} should be empty"

        # 他guildは無傷
        for table in ("memories", "chat_trace", "usage_log", "guild_plans", "run_log", "ingest_jobs"):
            assert self._count(conn, table, "g-2") == 1, f"{table} g-2 should remain"

    def test_purge_guild_keeps_running_purge_job(self, conn):
        """進行中の purge ジョブ自身は finish_job が完了記録できるよう残す。"""
        job_id = enqueue_job(conn, "g-1", JOB_INGEST, requested_by="test")
        conn.execute(
            "UPDATE ingest_jobs SET status = 'running' WHERE id = %s", (job_id,)
        )
        conn.commit()
        purge_guild_data(conn, "g-1")
        remaining = conn.execute(
            "SELECT status FROM ingest_jobs WHERE id = %s", (job_id,)
        ).fetchone()
        assert remaining is not None and remaining[0] == "running"


# ── log_run ───────────────────────────────────────────────────

class TestLogRun:
    def test_saves_log_entry(self, conn):
        log_run(conn, "run-1", "crawl", "success", "完了", "g-1")
        row = conn.execute(
            "SELECT run_id, guild_id, phase, status, message FROM run_log"
        ).fetchone()
        assert row == ("run-1", "g-1", "crawl", "success", "完了")

    def test_message_and_guild_can_be_none(self, conn):
        log_run(conn, "run-1", "crawl", "success")
        row = conn.execute("SELECT message, guild_id FROM run_log").fetchone()
        assert row == (None, None)

    def test_multiple_logs_accumulate(self, conn):
        log_run(conn, "run-1", "crawl", "success", "ch-1 完了")
        log_run(conn, "run-1", "crawl", "error", "ch-2 失敗")
        count = conn.execute("SELECT count(*) FROM run_log").fetchone()[0]
        assert count == 2


# ── usage_log ─────────────────────────────────────────────────

class TestUsageLog:
    def test_insert_and_summary(self, conn):
        insert_usage(conn, "g-1", "answer", "kimi", 1000, 200, 1200, 0.005, "u1")
        insert_usage(conn, "g-1", "rewrite", "gemini", 100, 20, 120, 0.001, "u1")
        insert_usage(conn, "g-2", "answer", "kimi", 500, 100, 600, 0.003, "u2")
        conn.commit()
        summary = fetch_usage_summary(conn)
        assert summary["total_calls"] == 3
        assert summary["total_tokens"] == 1200 + 120 + 600
        assert abs(summary["total_cost_usd"] - 0.009) < 1e-9
        kinds = {k["kind"]: k for k in summary["by_kind"]}
        assert kinds["answer"]["calls"] == 2
        guilds = {g["guild_id"]: g for g in summary["by_guild"]}
        assert abs(guilds["g-1"]["cost_usd"] - 0.006) < 1e-9

    def test_user_id_optional(self, conn):
        insert_usage(conn, "g-1", "answer", "kimi", 1, 1, 2, 0.0)
        conn.commit()
        row = conn.execute("SELECT user_id FROM usage_log").fetchone()
        assert row[0] is None

    def test_guilds_overview_includes_cost(self, conn):
        upsert_guild(conn, "g-1", "サーバー1")
        allow_channel(conn, "g-1", "ch-1", "general", "admin")
        insert_message(conn, _make_message(id="m1", guild_id="g-1"))
        insert_chunk(conn, "c1", "g-1", "m1", "ch-1", "本文")
        insert_usage(conn, "g-1", "answer", "kimi", 100, 10, 110, 0.004)
        conn.commit()
        overview = {g["guild_id"]: g for g in fetch_guilds_overview(conn)}
        g1 = overview["g-1"]
        assert g1["guild_name"] == "サーバー1"
        assert g1["allowed_count"] == 1
        assert g1["message_count"] == 1
        assert g1["chunk_count"] == 1
        assert abs(g1["cost_usd_this_month"] - 0.004) < 1e-9

    def test_recent_jobs_join_guild_name(self, conn):
        upsert_guild(conn, "g-1", "サーバー1")
        enqueue_job(conn, "g-1", JOB_INGEST, requested_by="admin")
        conn.commit()
        jobs = fetch_recent_jobs(conn, limit=10)
        assert len(jobs) == 1
        assert jobs[0]["guild_name"] == "サーバー1"
        assert jobs[0]["kind"] == JOB_INGEST
        assert jobs[0]["status"] == "queued"


# ── chat_trace（デバッグトレース・OI-21）────────────────────────

class TestChatTrace:
    def test_insert_round_trip(self, conn):
        sources = [
            {"channel_name": "general", "score": 0.91, "chunk_text": "本文"},
        ]
        insert_trace(
            conn, "g-1", "今日の予定は？",
            rewritten_query="予定",
            answer="たしか飲み会だよ",
            sources=sources,
            answer_model="deepseek/deepseek-v3.2",
            rerank_enabled=True,
            prompt_tokens=1200, completion_tokens=80,
            total_tokens=1300, cost_usd=0.0023, latency_ms=2500,
            user_id="u1",
        )
        conn.commit()
        row = conn.execute(
            "SELECT guild_id, user_id, question, rewritten_query, answer, "
            "sources, answer_model, rerank_enabled, prompt_tokens, "
            "completion_tokens, total_tokens, cost_usd, latency_ms "
            "FROM chat_trace"
        ).fetchone()
        assert row[0] == "g-1"
        assert row[1] == "u1"
        assert row[2] == "今日の予定は？"
        assert row[3] == "予定"
        assert row[4] == "たしか飲み会だよ"
        # JSONB は Python の list/dict として返る
        assert row[5][0]["channel_name"] == "general"
        assert row[5][0]["chunk_text"] == "本文"
        assert row[6] == "deepseek/deepseek-v3.2"
        assert row[7] is True
        assert row[8] == 1200
        assert row[10] == 1300
        assert abs(float(row[11]) - 0.0023) < 1e-9
        assert row[12] == 2500

    def test_minimal_fields(self, conn):
        # 任意フィールドは省略でき、sources は NULL でもよい
        insert_trace(conn, "g-1", "質問だけ")
        conn.commit()
        row = conn.execute(
            "SELECT question, sources, user_id, rerank_enabled FROM chat_trace"
        ).fetchone()
        assert row[0] == "質問だけ"
        assert row[1] is None
        assert row[2] is None
        assert row[3] is False


# ── memories（明示メモリ「覚えておいて」・OI-24）────────────────────

class TestMemories:
    def test_insert_and_fetch(self, conn):
        mid = insert_memory(
            conn, "g-1", "ケーキが好き",
            subject="かにじる", created_by="u1", source_channel_id="ch1",
        )
        assert isinstance(mid, int)
        rows = fetch_memories(conn, "g-1")
        assert len(rows) == 1
        r = rows[0]
        assert r["id"] == mid
        assert r["guild_id"] == "g-1"
        assert r["subject"] == "かにじる"
        assert r["content"] == "ケーキが好き"
        assert r["created_by"] == "u1"
        assert r["source_channel_id"] == "ch1"
        assert r["created_at"]  # ISO8601 が入っている

    def test_minimal_fields(self, conn):
        insert_memory(conn, "g-1", "3/25は誕生日")
        r = fetch_memories(conn, "g-1")[0]
        assert r["content"] == "3/25は誕生日"
        assert r["subject"] is None
        assert r["created_by"] is None
        assert r["source_channel_id"] is None

    def test_fetch_newest_first(self, conn):
        insert_memory(conn, "g-1", "古い")
        insert_memory(conn, "g-1", "新しい")
        rows = fetch_memories(conn, "g-1")
        # created_at DESC, id DESC: 後から入れた方が先頭
        assert rows[0]["content"] == "新しい"
        assert rows[1]["content"] == "古い"

    def test_guild_isolation(self, conn):
        insert_memory(conn, "g-1", "g1の事実")
        insert_memory(conn, "g-2", "g2の事実")
        assert [r["content"] for r in fetch_memories(conn, "g-1")] == ["g1の事実"]
        assert [r["content"] for r in fetch_memories(conn, "g-2")] == ["g2の事実"]

    def test_count(self, conn):
        assert count_memories(conn, "g-1") == 0
        insert_memory(conn, "g-1", "A")
        insert_memory(conn, "g-1", "B")
        insert_memory(conn, "g-2", "C")
        assert count_memories(conn, "g-1") == 2
        assert count_memories(conn, "g-2") == 1

    def test_delete(self, conn):
        mid = insert_memory(conn, "g-1", "消す対象")
        assert delete_memory(conn, "g-1", mid) is True
        assert count_memories(conn, "g-1") == 0
        # 既に無い／別 guild の id は False（消えない）
        assert delete_memory(conn, "g-1", mid) is False

    def test_delete_wrong_guild_keeps_row(self, conn):
        mid = insert_memory(conn, "g-1", "他guildからは消せない")
        assert delete_memory(conn, "g-2", mid) is False
        assert count_memories(conn, "g-1") == 1


# ── 真似っこモード personas / mimic_state（#49）─────────────────

from src import db as _db  # noqa: E402


class TestPersonas:
    def test_upsert_and_fetch(self, conn):
        card = {"personality": "明るい", "speech_style": "〜っす"}
        _db.upsert_persona_card(conn, "g1", "u1", "うさぎ", card, 42, created_by="adm")
        got = _db.fetch_persona_card(conn, "g1", "u1")
        assert got["display_name"] == "うさぎ"
        assert got["card"]["personality"] == "明るい"
        assert got["sample_count"] == 42
        assert got["consent"] == "unknown"

    def test_fetch_missing_returns_none(self, conn):
        assert _db.fetch_persona_card(conn, "g1", "nope") is None

    def test_upsert_overwrites_card_keeps_consent(self, conn):
        _db.set_persona_consent(conn, "g1", "u1", "optout")
        _db.upsert_persona_card(conn, "g1", "u1", "うさぎ", {"personality": "X"}, 1)
        got = _db.fetch_persona_card(conn, "g1", "u1")
        assert got["card"]["personality"] == "X"
        assert got["consent"] == "optout"  # consent は upsert で壊さない

    def test_consent_row_created_when_absent(self, conn):
        # カード未生成でも opt-out できる（consent だけの行が先に作られる）
        _db.set_persona_consent(conn, "g1", "u9", "optout")
        assert _db.get_persona_consent(conn, "g1", "u9") == "optout"

    def test_get_consent_default_unknown(self, conn):
        assert _db.get_persona_consent(conn, "g1", "none") == "unknown"

    def test_delete_persona(self, conn):
        _db.upsert_persona_card(conn, "g1", "u1", "X", {"personality": "p"}, 1)
        assert _db.delete_persona_card(conn, "g1", "u1") is True
        assert _db.fetch_persona_card(conn, "g1", "u1") is None


class TestFetchMemberMessages:
    def test_filters_guild_author_and_empty(self, conn):
        insert_message(conn, _make_message(id="m1", guild_id="g1", author_id="u1",
                                           content="あ", timestamp="2024-01-01T00:00:00+00:00"))
        insert_message(conn, _make_message(id="m2", guild_id="g1", author_id="u1",
                                           content="", has_attachment=True,
                                           timestamp="2024-01-02T00:00:00+00:00"))
        insert_message(conn, _make_message(id="m3", guild_id="g1", author_id="u2",
                                           content="別人", timestamp="2024-01-03T00:00:00+00:00"))
        insert_message(conn, _make_message(id="m4", guild_id="g2", author_id="u1",
                                           content="別guild", timestamp="2024-01-04T00:00:00+00:00"))
        rows = _db.fetch_member_messages(conn, "g1", "u1")
        contents = [r["content"] for r in rows]
        assert contents == ["あ"]  # 空content・別author・別guildは除外

    def test_limit(self, conn):
        for i in range(5):
            insert_message(conn, _make_message(
                id=f"m{i}", guild_id="g1", author_id="u1", content=f"c{i}",
                timestamp=f"2024-01-0{i+1}T00:00:00+00:00"))
        rows = _db.fetch_member_messages(conn, "g1", "u1", limit=3)
        assert len(rows) == 3

    def test_resolve_member_name_latest(self, conn):
        insert_message(conn, _make_message(id="m1", guild_id="g1", author_id="u1",
                                           author_name="旧名", timestamp="2024-01-01T00:00:00+00:00"))
        insert_message(conn, _make_message(id="m2", guild_id="g1", author_id="u1",
                                           author_name="新名", timestamp="2024-02-01T00:00:00+00:00"))
        assert _db.resolve_member_name(conn, "g1", "u1") == "新名"


class TestMimicState:
    def test_set_get_clear(self, conn):
        _db.set_mimic_state(conn, "g1", "c1", "u1", started_by="adm")
        st = _db.get_active_mimic(conn, "g1", "c1")
        assert st["author_id"] == "u1" and st["started_by"] == "adm"
        assert _db.clear_mimic_state(conn, "g1", "c1") is True
        assert _db.get_active_mimic(conn, "g1", "c1") is None

    def test_no_guild_fallback(self, conn):
        # channel 行のみ解決。別 channel には漏れない（guild fallback しない）
        _db.set_mimic_state(conn, "g1", "c1", "u1")
        assert _db.get_active_mimic(conn, "g1", "c2") is None

    def test_one_target_per_channel(self, conn):
        _db.set_mimic_state(conn, "g1", "c1", "u1")
        _db.set_mimic_state(conn, "g1", "c1", "u2")  # 上書き
        assert _db.get_active_mimic(conn, "g1", "c1")["author_id"] == "u2"


class TestMimicPurgeIntegrity:
    def test_purge_channel_keeps_personas_clears_state(self, conn):
        # personas は guild 資産＝ch削除で残る。mimic_state は該当chだけ消える。
        _db.upsert_persona_card(conn, "g1", "u1", "X", {"personality": "p"}, 1)
        _db.set_mimic_state(conn, "g1", "ch-1", "u1")
        _db.set_mimic_state(conn, "g1", "ch-2", "u1")
        from src.db import purge_channel_data
        purge_channel_data(conn, "g1", "ch-1")
        assert _db.fetch_persona_card(conn, "g1", "u1") is not None   # 残る
        assert _db.get_active_mimic(conn, "g1", "ch-1") is None       # 該当ch消える
        assert _db.get_active_mimic(conn, "g1", "ch-2") is not None   # 他chは無傷

    def test_purge_guild_clears_both(self, conn):
        _db.upsert_persona_card(conn, "g1", "u1", "X", {"personality": "p"}, 1)
        _db.set_mimic_state(conn, "g1", "ch-1", "u1")
        from src.db import purge_guild_data
        purge_guild_data(conn, "g1")
        assert _db.fetch_persona_card(conn, "g1", "u1") is None
        assert _db.get_active_mimic(conn, "g1", "ch-1") is None
