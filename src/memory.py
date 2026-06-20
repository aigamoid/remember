"""明示メモリ（memories）の読み取りプロバイダ。src/rag/engine.py / src/api.py から使用。

ユーザーが「覚えておいて」と教えた事実を guild 単位で取得し、回答プロンプトへ全件注入する
読み取り経路（OI-24）。Discord過去ログ（chunk_index）とは別の記憶領域。
TraceRecorder / UsageRecorder と同じく callable クラスで、engine から
`asyncio.to_thread` 経由で呼ばれる想定（同期DB I/O）。

接続失敗は空リストを返す＝メモリ無しで回答を続行させる（記憶の取得失敗で /chat を止めない）。
"""

from __future__ import annotations

from src import db


class MemoryProvider:
    """guild の「教わった事実」を全件返す callable（新しい順）。

    接続失敗時は空リストを返す（メモリ無しで回答を続行）。
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn

    def __call__(self, guild_id: str) -> list[dict]:
        try:
            conn = db.get_connection(self.dsn, init=False)
        except Exception as e:  # DB 未起動など
            print(f"[WARN] メモリ取得スキップ（接続失敗）: {e}")
            return []
        try:
            return db.fetch_memories(conn, guild_id)
        finally:
            conn.close()
