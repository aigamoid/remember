#!/usr/bin/env python3
"""ハイブリッド検索（#54）への移行スクリプト: Qdrant を sparse 付きで作り直して全再インデックス。

既存コレクション `waiwai_chunks` は dense 単体で作られているため、BM25 sparse ベクトルを
持たせるには「コレクション再作成 + 全ポイント再インデックス」が必要。データの正本は Postgres
`chunk_index` なので Qdrant を破棄しても安全（再 embedding で復元できる）。

やること:
  1. Qdrant コレクションを drop
  2. ensure_collection（dense + BM25 sparse 設定）で作り直し
  3. 全 guild の全チャンクを再 embedding + sparse 生成して登録（include_indexed=True）

実行方法:
    python scripts/migrate_hybrid_reindex.py            # 確認プロンプトあり
    python scripts/migrate_hybrid_reindex.py --yes      # プロンプトなし

注意: 実行中は検索結果が一時的に欠けるため、稼働サービスへの影響が小さい時間帯に行うこと。
まず staging（remember-vm）で実施してから本番へ。
"""

import argparse
import os
import sys
import uuid

from dotenv import load_dotenv

# scripts/ 配下から実行できるようプロジェクトルートを import パスに通す
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config  # noqa: E402
from src.db import get_connection, log_run  # noqa: E402
from src.embedder import Embedder  # noqa: E402
from src.indexer import run_indexer  # noqa: E402
from src.sparse import SparseEncoder  # noqa: E402
from src.vectorstore import VectorStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Qdrant を sparse 付きで作り直して全再インデックスする（#54）"
    )
    parser.add_argument(
        "--yes", action="store_true", help="確認プロンプトをスキップする"
    )
    args = parser.parse_args()

    load_dotenv()
    cfg = load_config()
    qdrant_cfg = cfg.get("qdrant", {})
    emb_cfg = cfg.get("embedding", {})

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
    sparse_encoder = SparseEncoder()

    if not args.yes:
        ans = input(
            f"コレクション '{store.collection}' を削除して全再インデックスします。"
            "続行しますか？ [y/N]: "
        )
        if ans.strip().lower() not in ("y", "yes"):
            print("中止しました")
            return

    conn = get_connection()
    run_id = str(uuid.uuid4())
    try:
        print("コレクションを削除中...")
        store.drop_collection()
        store.ensure_collection()  # dense + BM25 sparse 設定で作り直し
        print("全チャンクを再インデックス中（dense + sparse）...")
        done = run_indexer(
            conn, cfg, store, embedder,
            guild_id=None, include_indexed=True, sparse_encoder=sparse_encoder,
        )
        log_run(conn, run_id, "index", "success", f"hybrid移行: {done:,} 件")
        conn.commit()
        print(f"\n完了: {done:,} チャンクを dense + sparse で登録しました")
    except Exception as e:
        log_run(conn, run_id, "index", "error", f"hybrid移行失敗: {e}")
        conn.commit()
        print(f"\nエラーが発生しました: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
