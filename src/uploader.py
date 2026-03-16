"""Dify Knowledge API へチャンネルごとにアップロードする（Phase 3）。"""

from __future__ import annotations

import os
import sqlite3
import time

import requests

from src.db import (
    fetch_datasets_to_clean,
    fetch_pending_channels,
    init_upload_state,
    mark_channel_error,
    mark_channel_indexed,
    reset_all_upload_state,
    reset_upload_errors,
)
from src.formatter import format_message_line

def clean_datasets(conn: sqlite3.Connection, cfg: dict) -> int:
    """upload_state に記録されたデータセットを Dify から削除し、upload_state をリセットする。"""
    dify_cfg = cfg.get("dify", {})
    endpoint = dify_cfg["api_endpoint"]
    api_key = os.environ["DIFY_API_KEY"]
    api_timeout: int = dify_cfg.get("api_timeout", 30)

    rows = fetch_datasets_to_clean(conn)
    if not rows:
        print("  削除対象のデータセットなし")
        return 0

    headers = {"Authorization": f"Bearer {api_key}"}
    deleted = 0
    for _channel_id, channel_name, dataset_id in rows:
        try:
            resp = requests.delete(
                f"{endpoint}/datasets/{dataset_id}",
                headers=headers, timeout=api_timeout,
            )
            print(f"  {channel_name}: {resp.status_code}")
            deleted += 1
        except Exception as e:
            print(f"  {channel_name}: ERROR {e}")

    reset_count = reset_all_upload_state(conn)
    conn.commit()
    print(f"  {deleted}/{len(rows)} データセット削除、{reset_count} チャンネルをリセット")
    return deleted


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


def _create_dataset(endpoint: str, api_key: str, name: str, timeout: int) -> str:
    """Dify にナレッジベースを作成し dataset_id を返す。"""
    resp = requests.post(
        f"{endpoint}/datasets",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"name": name, "indexing_technique": "high_quality", "permission": "only_me"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _make_process_rule(separator: str, max_tokens: int) -> dict:
    """Dify 用の process_rule を組み立てる。"""
    return {
        "mode": "custom",
        "rules": {
            "pre_processing_rules": [
                {"id": "remove_extra_spaces", "enabled": False},
                {"id": "remove_urls_emails", "enabled": False},
            ],
            "segmentation": {"separator": separator, "max_tokens": max_tokens},
        },
    }


def _upload_document(
    endpoint: str, api_key: str, dataset_id: str, name: str, text: str,
    process_rule: dict, timeout: int,
) -> tuple[str, str]:
    """Dify にドキュメントを作成し (document_id, batch) を返す。"""
    resp = requests.post(
        f"{endpoint}/datasets/{dataset_id}/document/create-by-text",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "name": name,
            "text": text,
            "indexing_technique": "high_quality",
            "process_rule": process_rule,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["document"]["id"], data["batch"]


def _wait_for_indexing(
    endpoint: str, api_key: str, dataset_id: str, batch: str,
    poll_interval: int, max_wait: int, api_timeout: int,
) -> str:
    """ドキュメントのインデックス完了を待つ。最終ステータスを返す。"""
    headers = {"Authorization": f"Bearer {api_key}"}
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval
        resp = requests.get(
            f"{endpoint}/datasets/{dataset_id}/documents/{batch}/indexing-status",
            headers=headers, timeout=api_timeout,
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
    name_prefix: str = dify_cfg.get("dataset_name_prefix", "waiwai-")
    separator: str = dify_cfg.get("segmentation_separator", "\n\n")
    max_tokens: int = dify_cfg.get("segmentation_max_tokens", 1000)
    api_timeout: int = dify_cfg.get("api_timeout", 30)
    upload_timeout: int = dify_cfg.get("upload_timeout", 120)
    poll_interval: int = dify_cfg.get("indexing_poll_interval", 5)
    max_wait: int = dify_cfg.get("indexing_max_wait", 600)
    tz_offset: int = cfg.get("chunk", {}).get("timezone_offset", 9)

    process_rule = _make_process_rule(separator, max_tokens)

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
                endpoint, api_key, f"{name_prefix}{channel_name}", api_timeout,
            )
            doc_name, text = _build_channel_text(conn, channel_id, channel_name, tz_offset)
            print(f"    doc: {doc_name}", flush=True)
            doc_id, batch = _upload_document(
                endpoint, api_key, dataset_id, doc_name, text, process_rule, upload_timeout,
            )
            _wait_for_indexing(
                endpoint, api_key, dataset_id, batch, poll_interval, max_wait, api_timeout,
            )
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
