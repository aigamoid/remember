"""真似っこモード（#49）の読み取りプロバイダ。src/rag/engine.py / src/api.py から使用。

その channel で「いま誰を真似中か」（mimic_state）を解決し、対象者の人格カード
（personas）を返す読み取り経路。MemoryProvider（src/memory.py・OI-24）と同じく
callable クラスで、engine から `asyncio.to_thread` 経由で呼ばれる想定（同期DB I/O）。

スコープは channel 固定（設計 §7）。guild への fallback はしない＝宣言した channel
だけで真似が効く（意図せぬサーバー全体適用を防ぐ）。

接続失敗・該当なしは None を返す＝真似なし（素のれみ）で回答を続行させる
（mimic の取得失敗で /chat を止めない）。
"""

from __future__ import annotations

from src import db


class MimicProvider:
    """その channel で真似中の対象の人格カードを返す callable（#49）。

    戻り値: {"display_name": str, "card": dict}、または真似中でない/失敗時は None。
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn

    def __call__(self, guild_id: str, channel_id: str) -> dict | None:
        if not channel_id:
            return None
        try:
            conn = db.get_connection(self.dsn, init=False)
        except Exception as e:  # DB 未起動など
            print(f"[WARN] mimic 取得スキップ（接続失敗）: {e}")
            return None
        try:
            state = db.get_active_mimic(conn, guild_id, channel_id)
            if not state:
                return None
            persona = db.fetch_persona_card(conn, guild_id, state["author_id"])
            if not persona:
                return None
            card = persona.get("card") or {}
            if not isinstance(card, dict) or not card:
                return None
            return {
                "display_name": persona.get("display_name") or "",
                "card": card,
            }
        except Exception as e:  # 取得中の予期せぬ失敗でも回答は止めない
            print(f"[WARN] mimic 取得失敗（真似なしで続行）: {e}")
            return None
        finally:
            conn.close()


class MimicStore:
    """真似っこモードの書き込み/読み取り（#49）。src/api.py の /mimic/* から使用。

    consent 取得・発言サンプル取得・カード保存・真似状態の設定/解除を担う。
    DB I/O は同期で、各メソッドが接続を開閉する（MimicProvider と同じ流儀）。
    テストでは差し替え可能（FakeMimicStore）。例外は呼び出し側（api）が扱う。
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn

    def _conn(self):
        return db.get_connection(self.dsn, init=False)

    def get_consent(self, guild_id: str, author_id: str) -> str:
        conn = self._conn()
        try:
            return db.get_persona_consent(conn, guild_id, author_id)
        finally:
            conn.close()

    def set_consent(self, guild_id: str, author_id: str, consent: str) -> None:
        conn = self._conn()
        try:
            db.set_persona_consent(conn, guild_id, author_id, consent)
        finally:
            conn.close()

    def fetch_samples(
        self, guild_id: str, author_id: str, limit: int = 300
    ) -> list[dict]:
        conn = self._conn()
        try:
            return db.fetch_member_messages(conn, guild_id, author_id, limit)
        finally:
            conn.close()

    def resolve_name(self, guild_id: str, author_id: str) -> str | None:
        conn = self._conn()
        try:
            return db.resolve_member_name(conn, guild_id, author_id)
        finally:
            conn.close()

    def save_card(
        self,
        guild_id: str,
        author_id: str,
        display_name: str,
        card: dict,
        sample_count: int,
        created_by: str | None = None,
    ) -> None:
        conn = self._conn()
        try:
            db.upsert_persona_card(
                conn, guild_id, author_id, display_name, card,
                sample_count, created_by=created_by,
            )
        finally:
            conn.close()

    def set_state(
        self,
        guild_id: str,
        channel_id: str,
        author_id: str,
        started_by: str | None = None,
    ) -> None:
        conn = self._conn()
        try:
            db.set_mimic_state(conn, guild_id, channel_id, author_id, started_by)
        finally:
            conn.close()

    def clear_state(self, guild_id: str, channel_id: str) -> bool:
        conn = self._conn()
        try:
            return db.clear_mimic_state(conn, guild_id, channel_id)
        finally:
            conn.close()
