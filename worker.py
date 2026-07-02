#!/usr/bin/env python3
"""
worker.py - 取り込みワーカー常駐プロセス（compose の worker サービス）

Bot のスラッシュコマンド（/oracle allow, /oracle sync など）が投入したジョブを
順番に処理し、定期syncのスケジューリングも行う。

実行方法:
    python worker.py
    docker compose up -d worker
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

from src.api import build_engine
from src.config import load_config
from src.db import get_connection
from src.embedder import Embedder
from src.sparse import SparseEncoder
from src.vectorstore import VectorStore
from src.worker import IngestWorker


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("エラー: DISCORD_TOKEN が設定されていません (.env を確認してください)")
        sys.exit(1)

    cfg = load_config()
    qdrant_cfg = cfg.get("qdrant", {})
    emb_cfg = cfg.get("embedding", {})
    worker_cfg = cfg.get("worker", {})

    # QDRANT_URL はコンテナ内からの接続用オーバーライド（compose では http://qdrant:6333）
    store = VectorStore(
        url=os.environ.get("QDRANT_URL")
        or qdrant_cfg.get("url", "http://localhost:6333"),
        collection=qdrant_cfg.get("collection", "waiwai_chunks"),
        vector_size=emb_cfg.get("dimensions", 1536),
    )
    embedder = Embedder(
        model=emb_cfg.get("model", "text-embedding-3-small"),
        dimensions=emb_cfg.get("dimensions", 1536),
    )
    store.ensure_collection()
    conn = get_connection()

    # ハイブリッド検索（#54）: rag.hybrid.enabled=true のときだけ取り込み時に BM25 sparse を生成。
    sparse_encoder = None
    if cfg.get("rag", {}).get("hybrid", {}).get("enabled", False):
        sparse_encoder = SparseEncoder()

    # 自動記憶（#56 案C）: rag.auto_memory.enabled=true のときだけ engine を組み立てて渡す。
    # engine 側も同フラグを見るので二重ガード（既定OFF＝従来どおり明示メモリのみ）。
    engine = None
    if cfg.get("rag", {}).get("auto_memory", {}).get("enabled", False):
        engine = build_engine(cfg)

    worker = IngestWorker(
        conn, cfg, store, embedder, token,
        poll_interval=worker_cfg.get("poll_interval_seconds", 10),
        sync_interval_hours=worker_cfg.get("sync_interval_hours", 24),
        sparse_encoder=sparse_encoder,
        engine=engine,
    )
    try:
        asyncio.run(worker.run_forever())
    except KeyboardInterrupt:
        print("\nワーカーを停止しました")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
