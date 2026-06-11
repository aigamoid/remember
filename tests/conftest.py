"""pytest 共通フィクスチャ: Postgres テスト接続

DB依存テストは実際の Postgres（oracle_test データベース）に対して実行する。
事前に `docker compose up -d postgres` を実行しておくこと。
接続できない環境では該当テストを skip する。

接続先は環境変数 TEST_DATABASE_URL で上書きできる。
"""

from __future__ import annotations

import os

import psycopg
import pytest
from psycopg import conninfo

from src.db import init_schema

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://oracle:oracle@localhost:5432/oracle_test",
)

_TRUNCATE = (
    "TRUNCATE guilds, allowed_channels, messages, attachments, "
    "crawl_state, chunk_index, ingest_jobs, run_log RESTART IDENTITY CASCADE"
)


def _ensure_test_db() -> None:
    """oracle_test データベースが無ければ作成する（postgres DB 経由）。"""
    params = conninfo.conninfo_to_dict(TEST_DSN)
    dbname = params.get("dbname") or "oracle_test"
    admin = {**params, "dbname": "postgres"}
    with psycopg.connect(**admin, autocommit=True) as ac:
        row = ac.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
        ).fetchone()
        if row is None:
            ac.execute(f'CREATE DATABASE "{dbname}"')


@pytest.fixture(scope="session")
def pg_conn():
    try:
        _ensure_test_db()
        c = psycopg.connect(TEST_DSN)
    except psycopg.OperationalError as e:
        pytest.skip(
            f"Postgres に接続できません（docker compose up -d postgres を実行してください）: {e}"
        )
    init_schema(c)
    yield c
    c.close()


@pytest.fixture
def conn(pg_conn):
    """各テスト用にテーブルを空にした接続を提供する。"""
    pg_conn.rollback()
    pg_conn.execute(_TRUNCATE)
    pg_conn.commit()
    yield pg_conn
    pg_conn.rollback()
