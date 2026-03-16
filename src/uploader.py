"""Dify Knowledge API へチャンネルごとにアップロードする（Phase 3）。"""

from __future__ import annotations

import os
import sqlite3
import time

import requests

from src.db import (
    fetch_pending_channels,
    init_upload_state,
    mark_channel_error,
    mark_channel_indexed,
    reset_upload_errors,
)
from src.formatter import format_message_line

_NAME_PREFIX = "waiwai-"


def _build_channel_text(
    conn: sqlite3.Connection, channel_id: str, channel_name: str, tz_offset: int,
) -> tuple[str, str]:
    """チャンネルのメッセージを連結し (doc_name, text) を返す。"""
    rows = conn.execute(
        "SELECT author_name, content, timestamp, has_attachment "
        "FROM messages WHERE channel_id = ? ORDER BY timestamp ASC",
        (channel_id,),
    ).fetchall()

    lines = [
        format_message_line(a, c, ts, bool(h), tz_offset) for a, c, ts, h in rows
    ]
    return (channel_name, "\n\n".join(lines))


def _create_dataset(endpoint: str, api_key: str, name: str) -> str:
    """Dify にナレッジベースを作成し dataset_id を返す。"""
    resp = requests.post(
        f"{endpoint}/datasets",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"name": name, "indexing_technique": "high_quality", "permission": "only_me"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


_PROCESS_RULE = {
    "mode": "custom",
    "rules": {
        "pre_processing_rules": [
            {"id": "remove_extra_spaces", "enabled": False},
            {"id": "remove_urls_emails", "enabled": False},
        ],
        "segmentation": {"separator": "\n\n", "max_tokens": 500},
    },
}


def _upload_document(
    endpoint: str, api_key: str, dataset_id: str, name: str, text: str,
) -> tuple[str, str]:
    """Dify にドキュメントを作成し (document_id, batch) を返す。"""
    resp = requests.post(
        f"{endpoint}/datasets/{dataset_id}/document/create-by-text",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "name": name,
            "text": text,
            "indexing_technique": "high_quality",
            "process_rule": _PROCESS_RULE,
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["document"]["id"], data["batch"]


def _wait_for_indexing(
    endpoint: str, api_key: str, dataset_id: str, batch: str,
    poll_interval: int = 5, max_wait: int = 600,
) -> str:
    """ドキュメントのインデックス完了を待つ。最終ステータスを返す。"""
    headers = {"Authorization": f"Bearer {api_key}"}
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval
        resp = requests.get(
            f"{endpoint}/datasets/{dataset_id}/documents/{batch}/indexing-status",
            headers=headers, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        status = data[0].get("indexing_status", "") if data else ""
        if status == "completed":
            return status
        if status == "error":
            raise RuntimeError(f"Indexing failed: {data[0].get('error', 'unknown')}")
        print(f"    indexing... ({elapsed}s)", flush=True)
    raise TimeoutError(f"Indexing not completed within {max_wait}s")


def run_uploader(
    conn: sqlite3.Connection,
    cfg: dict,
    run_id: str,
    retry_errors: bool = False,
) -> int:
    """チャンネルごとにナレッジベース作成 → ドキュメントアップロードを行う。"""
    dify_cfg = cfg.get("dify", {})
    endpoint = dify_cfg["api_endpoint"]
    api_key = os.environ["DIFY_API_KEY"]
    tz_offset: int = cfg.get("chunk", {}).get("timezone_offset", 9)

    init_upload_state(conn)
    conn.commit()

    if retry_errors:
        reset_count = reset_upload_errors(conn)
        conn.commit()
        print(f"  {reset_count:,} 件のエラーを pending に戻しました")

    channels = fetch_pending_channels(conn)
    total = len(channels)
    if total == 0:
        print("  アップロード対象なし")
        return 0

    done = 0
    for channel_id, channel_name, existing_dataset_id in channels:
        dataset_id = existing_dataset_id
        try:
            dataset_id = existing_dataset_id or _create_dataset(
                endpoint, api_key, f"{_NAME_PREFIX}{channel_name}",
            )
            doc_name, text = _build_channel_text(conn, channel_id, channel_name, tz_offset)
            print(f"    doc: {doc_name}", flush=True)
            doc_id, batch = _upload_document(endpoint, api_key, dataset_id, doc_name, text)
            _wait_for_indexing(endpoint, api_key, dataset_id, batch)
            mark_channel_indexed(conn, channel_id, dataset_id, doc_id)
        except Exception as e:
            mark_channel_error(
                conn, channel_id, str(e), dataset_id=dataset_id,
            )
            print(f"  ERROR {channel_name}: {e}")
        conn.commit()
        done += 1
        print(f"  {done}/{total} チャンネル完了: #{channel_name}")

    return done
