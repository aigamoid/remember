"""src/chunker.py のテスト（実Postgresを使用・tests/conftest.py の conn フィクスチャ）"""

from __future__ import annotations

from src.chunker import _build_chunk_text, _is_noise, generate_chunk_id, run_chunker
from src.db import count_chunks, insert_chunk


def _insert_msg(
    conn,
    msg_id: str,
    channel_id: str,
    content: str,
    has_attachment: int = 0,
    author: str = "user",
    timestamp: str = "2024-01-01T00:00:00+00:00",
    guild_id: str = "g1",
) -> None:
    conn.execute(
        "INSERT INTO messages "
        "(id, guild_id, channel_id, channel_name, author_id, author_name, content, timestamp, has_attachment) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (msg_id, guild_id, channel_id, "ch", "u1", author, content, timestamp, has_attachment),
    )


def _make_cfg(
    time_gap_minutes: int = 60,
    max_chunk_messages: int = 30,
    min_content_length: int = 10,
    short_reply_max_chars: int = 10,
) -> dict:
    return {"chunk": {
        "time_gap_minutes": time_gap_minutes,
        "max_chunk_messages": max_chunk_messages,
        "min_content_length": min_content_length,
        "short_reply_max_chars": short_reply_max_chars,
        "timezone_offset": 9,
    }}


# ── generate_chunk_id ──────────────────────────────────────────────────────

class TestGenerateChunkId:
    def test_returns_32_char_hex(self):
        result = generate_chunk_id("msg-1")
        assert isinstance(result, str)
        assert len(result) == 32

    def test_is_deterministic(self):
        assert generate_chunk_id("msg-1") == generate_chunk_id("msg-1")

    def test_differs_by_anchor(self):
        assert generate_chunk_id("msg-1") != generate_chunk_id("msg-2")


# ── _build_chunk_text ──────────────────────────────────────────────────────

class TestBuildChunkText:
    def test_timestamp_converted_to_jst(self):
        rows = [("id1", "UserA", "hello", "2024-01-01T12:00:00+00:00", 0)]
        text = _build_chunk_text(rows, tz_offset=9)
        assert "[2024-01-01 21:00]" in text  # UTC+9

    def test_contains_author_and_content(self):
        rows = [("id1", "UserA", "てすと", "2024-01-01T00:00:00+00:00", 0)]
        text = _build_chunk_text(rows, tz_offset=9)
        assert "UserA" in text
        assert "てすと" in text

    def test_attachment_flag_appended(self):
        rows = [("id1", "UserA", "画像です", "2024-01-01T00:00:00+00:00", 1)]
        text = _build_chunk_text(rows, tz_offset=9)
        assert "[添付ファイルあり]" in text

    def test_no_attachment_flag_when_false(self):
        rows = [("id1", "UserA", "テキストのみ", "2024-01-01T00:00:00+00:00", 0)]
        text = _build_chunk_text(rows, tz_offset=9)
        assert "[添付ファイルあり]" not in text

    def test_multiple_rows_joined_by_newline(self):
        rows = [
            ("id1", "UserA", "一行目", "2024-01-01T00:00:00+00:00", 0),
            ("id2", "UserB", "二行目", "2024-01-01T00:01:00+00:00", 0),
        ]
        text = _build_chunk_text(rows, tz_offset=9)
        assert text.count("\n") == 1


# ── insert_chunk / count_chunks ────────────────────────────────────────────

class TestInsertChunk:
    def test_saves_with_pending_status(self, conn):
        insert_chunk(conn, "cid1", "g1", "mid1", "ch1", "text")
        row = conn.execute(
            "SELECT anchor_msg_id, channel_id, status FROM chunk_index WHERE chunk_id='cid1'"
        ).fetchone()
        assert row is not None
        assert row[0] == "mid1"
        assert row[1] == "ch1"
        assert row[2] == "pending"

    def test_is_idempotent(self, conn):
        insert_chunk(conn, "cid1", "g1", "mid1", "ch1", "text")
        insert_chunk(conn, "cid1", "g1", "mid1", "ch1", "text")
        assert count_chunks(conn) == 1

    def test_count_chunks_no_filter(self, conn):
        insert_chunk(conn, "c1", "g1", "m1", "ch1", "a")
        insert_chunk(conn, "c2", "g1", "m2", "ch1", "b")
        assert count_chunks(conn) == 2

    def test_count_chunks_by_status(self, conn):
        insert_chunk(conn, "c1", "g1", "m1", "ch1", "a")
        conn.execute("UPDATE chunk_index SET status='indexed' WHERE chunk_id='c1'")
        insert_chunk(conn, "c2", "g1", "m2", "ch1", "b")
        assert count_chunks(conn, status="pending") == 1
        assert count_chunks(conn, status="indexed") == 1

    def test_count_chunks_unknown_status_returns_zero(self, conn):
        insert_chunk(conn, "c1", "g1", "m1", "ch1", "a")
        assert count_chunks(conn, status="no_such_status") == 0


# ── run_chunker（時間ギャップ方式） ─────────────────────────────────────────

class TestRunChunker:
    def test_messages_within_gap_form_single_chunk(self, conn):
        """1分間隔（< 60分）のメッセージは同一チャンクにまとめられる。"""
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ", timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "これも十分な長さです", timestamp="2024-01-01T00:01:00+00:00")
        conn.commit()

        total = run_chunker(conn, _make_cfg(), "run-1")
        assert total == 1
        assert count_chunks(conn) == 1

    def test_messages_exceeding_gap_split_into_chunks(self, conn):
        """61分間隔（>= 60分）のメッセージは別チャンクになる。"""
        _insert_msg(conn, "m1", "ch1", "最初のメッセージ内容です", timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "61分後のメッセージ内容です", timestamp="2024-01-01T01:01:00+00:00")
        conn.commit()

        total = run_chunker(conn, _make_cfg(), "run-1")
        assert total == 2
        assert count_chunks(conn) == 2

    def test_boundary_59min_same_chunk(self, conn):
        """59分間隔は同一チャンク（< 60分）。"""
        _insert_msg(conn, "m1", "ch1", "最初のメッセージ", timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "59分後のメッセージ", timestamp="2024-01-01T00:59:00+00:00")
        conn.commit()

        total = run_chunker(conn, _make_cfg(time_gap_minutes=60), "run-1")
        assert total == 1

    def test_boundary_60min_split(self, conn):
        """60分間隔は別チャンク（>= 60分）。"""
        _insert_msg(conn, "m1", "ch1", "最初のメッセージ内容です", timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "60分後のメッセージ内容です", timestamp="2024-01-01T01:00:00+00:00")
        conn.commit()

        total = run_chunker(conn, _make_cfg(time_gap_minutes=60), "run-1")
        assert total == 2

    def test_max_chunk_messages_triggers_split(self, conn):
        """max_chunk_messages 超過でチャンクが分割される。"""
        for i in range(6):
            ts = f"2024-01-01T00:0{i}:00+00:00"
            _insert_msg(conn, f"m{i}", "ch1", f"メッセージ{i}番目の内容", timestamp=ts)
        conn.commit()

        total = run_chunker(conn, _make_cfg(time_gap_minutes=60, max_chunk_messages=3), "run-1")
        assert total == 2

    def test_short_content_without_attachment_skipped(self, conn):
        _insert_msg(conn, "m1", "ch1", "ab", has_attachment=0)  # 2文字 < min_len=10
        conn.commit()
        assert run_chunker(conn, _make_cfg(), "run-1") == 0

    def test_short_content_with_attachment_not_skipped(self, conn):
        _insert_msg(conn, "m1", "ch1", "ab", has_attachment=1)  # 添付あり → スキップしない
        conn.commit()
        assert run_chunker(conn, _make_cfg(), "run-1") == 1

    def test_empty_messages_returns_zero(self, conn):
        assert run_chunker(conn, _make_cfg(), "run-1") == 0

    def test_channel_boundary_isolation(self, conn):
        _insert_msg(conn, "a1", "ch-A", "チャンネルAのメッセージ", timestamp="2024-01-01T00:01:00+00:00")
        _insert_msg(conn, "b1", "ch-B", "チャンネルBのメッセージ", timestamp="2024-01-01T00:02:00+00:00")
        conn.commit()

        run_chunker(conn, _make_cfg(), "run-1")
        anchors = {r[0] for r in conn.execute("SELECT anchor_msg_id FROM chunk_index").fetchall()}
        assert "a1" in anchors
        assert "b1" in anchors

    def test_guild_filter_processes_only_target_guild(self, conn):
        """guild_id 指定時は他サーバーのメッセージをチャンク化しない。"""
        _insert_msg(conn, "a1", "ch-A", "ギルド1のメッセージです", guild_id="g1")
        _insert_msg(conn, "b1", "ch-B", "ギルド2のメッセージです", guild_id="g2")
        conn.commit()

        total = run_chunker(conn, _make_cfg(), "run-1", guild_id="g1")
        assert total == 1
        rows = conn.execute("SELECT DISTINCT guild_id FROM chunk_index").fetchall()
        assert rows == [("g1",)]

    def test_chunk_records_guild_id(self, conn):
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ", guild_id="g9")
        conn.commit()

        run_chunker(conn, _make_cfg(), "run-1")
        row = conn.execute("SELECT guild_id FROM chunk_index").fetchone()
        assert row[0] == "g9"

    def test_idempotency_db_count_unchanged_on_rerun(self, conn):
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ")
        conn.commit()

        run_chunker(conn, _make_cfg(), "run-1")
        first_count = count_chunks(conn)
        run_chunker(conn, _make_cfg(), "run-2")
        assert count_chunks(conn) == first_count

    def test_chunk_text_contains_all_messages_in_group(self, conn):
        """同一チャンク内に全メッセージが含まれていること。"""
        _insert_msg(conn, "m1", "ch1", "最初のテストメッセージです", author="UserA",
                    timestamp="2024-01-01T12:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "次のテストメッセージです", author="UserB",
                    timestamp="2024-01-01T12:01:00+00:00")
        conn.commit()

        run_chunker(conn, _make_cfg(), "run-1")
        row = conn.execute("SELECT chunk_text FROM chunk_index").fetchone()
        assert row is not None
        assert "UserA" in row[0]
        assert "UserB" in row[0]
        assert "最初のテストメッセージです" in row[0]
        assert "次のテストメッセージです" in row[0]
        assert "[2024-01-01 21:00]" in row[0]  # UTC→JST(+9)

    def test_resolves_mentions_in_chunk_text(self, conn):
        """本文中の <@author_id> が @表示名 に解決される（OI-18）"""
        # author_id=111 が「アリス」として発言 → 別メッセージの <@111> を解決できる
        _insert_msg(conn, "m1", "ch1", "おはようみんな今日もよろしく", author="アリス",
                    timestamp="2024-01-01T12:00:00+00:00")
        conn.execute(
            "INSERT INTO messages "
            "(id, guild_id, channel_id, channel_name, author_id, author_name, content, timestamp, has_attachment) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            ("m0", "g1", "ch1", "ch", "111", "アリス", "やっほー元気にしてた？",
             "2023-12-31T12:00:00+00:00", 0),
        )
        _insert_msg(conn, "m2", "ch1", "ねえ <@111> ちょっと聞きたい", author="ボブ",
                    timestamp="2024-01-01T12:01:00+00:00")
        conn.commit()

        run_chunker(conn, _make_cfg(), "run-1")
        texts = " ".join(r[0] for r in conn.execute("SELECT chunk_text FROM chunk_index").fetchall())
        assert "@アリス" in texts
        assert "<@111>" not in texts


# ── _is_noise ───────────────────────────────────────────────────────────────

class TestIsNoise:
    def test_has_attachment_always_false(self):
        assert _is_noise("ab", True, 10) is False

    def test_short_content_without_attachment(self):
        assert _is_noise("abc", False, 10) is True

    def test_long_enough_content_not_noise(self):
        assert _is_noise("十分な長さのメッセージ", False, 10) is False

    def test_url_only_is_noise(self):
        assert _is_noise("https://example.com/foo", False, 5) is True

    def test_url_with_leading_space_is_noise(self):
        assert _is_noise("  https://example.com/foo  ", False, 5) is True

    def test_url_with_text_is_not_noise(self):
        assert _is_noise("見て https://example.com", False, 5) is False

    def test_at_here_is_noise(self):
        assert _is_noise("@here", False, 5) is True

    def test_at_everyone_is_noise(self):
        assert _is_noise("@everyone", False, 5) is True

    def test_at_here_with_spaces_is_noise(self):
        assert _is_noise("@here  ", False, 5) is True

    def test_at_mention_user_is_not_noise(self):
        assert _is_noise("@username みてみて", False, 5) is False

    def test_whitespace_only_is_noise(self):
        assert _is_noise("   ", False, 10) is True


# ── ノイズフィルター統合テスト ───────────────────────────────────────────────

class TestRunChunkerNoiseFilter:
    def test_url_only_message_skipped(self, conn):
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ",
                    timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "https://example.com/very/long/url/here",
                    timestamp="2024-01-01T00:01:00+00:00")
        conn.commit()

        run_chunker(conn, _make_cfg(), "run-1")
        row = conn.execute("SELECT chunk_text FROM chunk_index").fetchone()
        assert "example.com" not in row[0]

    def test_at_here_skipped(self, conn):
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ",
                    timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "@here",
                    timestamp="2024-01-01T00:01:00+00:00")
        conn.commit()

        run_chunker(conn, _make_cfg(), "run-1")
        row = conn.execute("SELECT chunk_text FROM chunk_index").fetchone()
        assert "@here" not in row[0]

    def test_whitespace_only_skipped(self, conn):
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ",
                    timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "   ",
                    timestamp="2024-01-01T00:01:00+00:00")
        conn.commit()

        total = run_chunker(conn, _make_cfg(), "run-1")
        assert total == 1
        row = conn.execute("SELECT chunk_text FROM chunk_index").fetchone()
        assert row[0].count("\n") == 0  # 1行のみ


# ── 短文吸収テスト ──────────────────────────────────────────────────────────

class TestRunChunkerShortReply:
    def test_short_reply_absorbed_into_previous_chunk(self, conn):
        """短文（≤10文字）はギャップ内なら直前チャンクに吸収される。"""
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ",
                    timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "はい",  # 2文字 <= 10
                    timestamp="2024-01-01T00:05:00+00:00")
        conn.commit()

        total = run_chunker(conn, _make_cfg(), "run-1")
        assert total == 1
        row = conn.execute("SELECT chunk_text FROM chunk_index").fetchone()
        assert "はい" in row[0]

    def test_short_reply_after_large_gap_starts_new_chunk(self, conn):
        """長時間ギャップ後の短文は吸収されず通常フロー（ノイズフィルターを通る）。"""
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ",
                    timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "十分な長さの別メッセージ",  # 通常メッセージ（新チャンク）
                    timestamp="2024-01-01T02:00:00+00:00")
        conn.commit()

        total = run_chunker(conn, _make_cfg(), "run-1")
        assert total == 2

    def test_short_reply_after_large_gap_alone_is_filtered(self, conn):
        """長時間ギャップ後の短文は通常フロー → min_content_length で除去。"""
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ",
                    timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "はい",  # 2文字 < min_len=10、ギャップ後
                    timestamp="2024-01-01T02:00:00+00:00")
        conn.commit()

        total = run_chunker(conn, _make_cfg(), "run-1")
        assert total == 1  # 「はい」は除去されて m1 のチャンクのみ

    def test_at_here_not_absorbed_even_within_gap(self, conn):
        """@here は短文でもギャップ内でも吸収しない。"""
        _insert_msg(conn, "m1", "ch1", "十分な長さのメッセージ",
                    timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "@here",
                    timestamp="2024-01-01T00:05:00+00:00")
        conn.commit()

        total = run_chunker(conn, _make_cfg(), "run-1")
        assert total == 1
        row = conn.execute("SELECT chunk_text FROM chunk_index").fetchone()
        assert "@here" not in row[0]

    def test_max_chunk_messages_respected_with_short_replies(self, conn):
        """短文吸収時も max_chunk_messages を超えたらフラッシュし、次の通常メッセージで新チャンク。"""
        _insert_msg(conn, "m1", "ch1", "通常メッセージその一つ目",   # 12文字（通常）
                    timestamp="2024-01-01T00:00:00+00:00")
        _insert_msg(conn, "m2", "ch1", "は",                          # 1文字（短文）
                    timestamp="2024-01-01T00:01:00+00:00")
        _insert_msg(conn, "m3", "ch1", "うん",                        # 2文字（短文）→ len=3 >= max=3 でフラッシュ
                    timestamp="2024-01-01T00:02:00+00:00")
        _insert_msg(conn, "m4", "ch1", "通常メッセージその二つ目",   # 12文字（通常）→ 新チャンク
                    timestamp="2024-01-01T00:03:00+00:00")
        conn.commit()

        # max=3: [m1,m2,m3] でフラッシュ → [m4] でフラッシュ = 2チャンク
        total = run_chunker(conn, _make_cfg(max_chunk_messages=3), "run-1")
        assert total == 2
