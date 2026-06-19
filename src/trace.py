"""回答トレースの記録（chat_trace）。src/rag/engine.py / src/api.py から使用。

1回の /chat（質問→書き換え→検索→回答）の中身（質問・書き換え後クエリ・ヒットした
チャンク・最終回答・トークン/コスト）を chat_trace テーブルに1行で残す、デバッグ/開発用の
機能（OI-21）。プライバシー上、本番では config の rag.debug_trace=false で無効化する。

usage_log と同じく「記録失敗は回答を止めない」設計（DB 障害時でも /chat は動き続ける）。
"""

from __future__ import annotations

from src import db


class TraceRecorder:
    """回答トレース1件を chat_trace に書き込む callable。

    engine から `asyncio.to_thread` 経由で呼ばれる想定（同期DB I/O）。
    例外は握りつぶす — トレースの失敗で回答を落とさないため（UsageRecorder と同様）。
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn

    def __call__(self, row: dict) -> None:
        if not row:
            return
        try:
            conn = db.get_connection(self.dsn, init=False)
        except Exception as e:  # DB 未起動など
            print(f"[WARN] trace記録スキップ（接続失敗）: {e}")
            return
        try:
            db.insert_trace(conn, **row)
            conn.commit()
        except Exception as e:
            print(f"[WARN] trace記録失敗: {e}")
        finally:
            conn.close()
