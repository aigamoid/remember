"""同意ログ（公開/課金前の法務要件・#41 / OI-48）のテスト（実Postgres）。

`/oracle allow`/`allowall` の初回に取得する明示同意を consent_log に記録し、
サーバー×規約版で「同意済みか」を判定する DB/Store ロジックを検証する。
Store は自前で接続を張るため TEST_DSN を渡す（test_store と同じ構成）。
"""

from __future__ import annotations

import asyncio

from src.db import has_consented, record_consent, upsert_guild

from moimoichan_Discordbot.store import Store
from tests.conftest import TEST_DSN

GUILD = "g-consent"
TERMS = "v1-2026-06-30"


def _store() -> Store:
    return Store(dsn=TEST_DSN)


class TestConsentDb:
    def test_unconsented_guild_returns_false(self, conn):
        upsert_guild(conn, GUILD, "テスト鯖")
        conn.commit()
        assert has_consented(conn, GUILD, TERMS) is False

    def test_record_then_consented(self, conn):
        upsert_guild(conn, GUILD, "テスト鯖")
        conn.commit()
        record_consent(
            conn, GUILD, "admin-1", TERMS, "allow",
            [{"id": "c1", "name": "general"}],
        )
        assert has_consented(conn, GUILD, TERMS) is True

    def test_different_terms_version_requires_reconsent(self, conn):
        upsert_guild(conn, GUILD, "テスト鯖")
        conn.commit()
        record_consent(conn, GUILD, "admin-1", TERMS, "allow", None)
        # 規約版を上げると、新しい版には未同意扱いになる（再同意が必要）。
        assert has_consented(conn, GUILD, TERMS) is True
        assert has_consented(conn, GUILD, "v2-2099-01-01") is False

    def test_channels_jsonb_roundtrip(self, conn):
        upsert_guild(conn, GUILD, "テスト鯖")
        conn.commit()
        chans = [{"id": "c1", "name": "general"}, {"id": "c2", "name": "random"}]
        record_consent(conn, GUILD, "admin-1", TERMS, "allowall", chans)
        row = conn.execute(
            "SELECT admin_id, scope, channels FROM consent_log WHERE guild_id = %s",
            (GUILD,),
        ).fetchone()
        assert row[0] == "admin-1"
        assert row[1] == "allowall"
        assert row[2] == chans  # JSONB が往復で保持される


class TestConsentStore:
    def test_store_record_and_check(self, conn):
        upsert_guild(conn, GUILD, "テスト鯖")
        conn.commit()
        store = _store()
        assert asyncio.run(store.has_consented(GUILD, TERMS)) is False
        asyncio.run(
            store.record_consent(
                GUILD, "admin-9", TERMS, "allow", [{"id": "c1", "name": "general"}]
            )
        )
        assert asyncio.run(store.has_consented(GUILD, TERMS)) is True
