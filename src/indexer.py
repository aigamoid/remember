"""チャンクを embedding して Qdrant に登録するロジック（Phase 4）。indexer.py から使用。"""

from __future__ import annotations

import sqlite3

from src.db import fetch_chunks_for_indexing, mark_chunks_indexed
from src.embedder import Embedder
from src.vectorstore import VectorStore


def build_embed_text(chunk_text: str, context_text: str | None) -> str:
    """embedding 対象テキストを組み立てる。
    context_text があれば先頭に付ける（Contextual Retrieval）。"""
    if context_text:
        return f"{context_text}\n\n{chunk_text}"
    return chunk_text


def run_indexer(
    conn: sqlite3.Connection,
    cfg: dict,
    store: VectorStore,
    embedder: Embedder,
    include_indexed: bool = False,
) -> int:
    """未インデックスのチャンクを Qdrant に登録する。登録件数を返す。"""
    guild_id = str(cfg["guild_id"])
    batch_size: int = cfg.get("embedding", {}).get("batch_size", 100)

    rows = fetch_chunks_for_indexing(conn, include_indexed=include_indexed)
    total = len(rows)
    print(f"  インデックス対象チャンク: {total:,} 件")
    if total == 0:
        return 0

    store.ensure_collection()

    done = 0
    for start in range(0, total, batch_size):
        batch = rows[start : start + batch_size]
        texts = [
            build_embed_text(chunk_text, context_text)
            for _, _, _, chunk_text, context_text, _ in batch
        ]
        vectors = embedder.embed(texts)
        payloads = [
            {
                "guild_id": guild_id,
                "chunk_id": chunk_id,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "chunk_text": chunk_text,
                "context_text": context_text,
                "anchor_timestamp": anchor_ts,
            }
            for chunk_id, channel_id, channel_name, chunk_text, context_text, anchor_ts in batch
        ]
        store.upsert(payloads, vectors)
        mark_chunks_indexed(conn, [p["chunk_id"] for p in payloads])
        conn.commit()

        done += len(batch)
        if done % 1000 < batch_size:
            print(f"  {done:,} / {total:,} 件登録済み")

    return done
