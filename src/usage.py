"""利用量計測（usage_log）のコスト算出と記録。src/rag/engine.py / src/api.py から使用。

OpenAI/OpenRouter のレスポンスに含まれる usage（トークン数）を拾い、
config.yml の pricing 単価表で推定コスト(USD)を計算して usage_log に記録する。
記録失敗は回答処理を止めない（DB 障害時でも /chat は動き続ける設計）。
"""

from __future__ import annotations

from src import db


def compute_cost(
    pricing: dict,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """単価表(USD/100万トークン)から推定コスト(USD)を算出する。未掲載モデルは 0。"""
    if not model:
        return 0.0
    price = pricing.get(model)
    if not price:
        return 0.0
    inp = float(price.get("input", 0.0))
    outp = float(price.get("output", 0.0))
    return (prompt_tokens * inp + completion_tokens * outp) / 1_000_000


class UsageRecorder:
    """usage イベントのリストを usage_log にまとめて書き込む callable。

    engine から `asyncio.to_thread` 経由で呼ばれる想定（同期DB I/O）。
    例外は握りつぶす — 計測の失敗で回答を落とさないため。
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn

    def __call__(self, events: list[dict]) -> None:
        if not events:
            return
        try:
            conn = db.get_connection(self.dsn, init=False)
        except Exception as e:  # DB 未起動など
            print(f"[WARN] usage記録スキップ（接続失敗）: {e}")
            return
        try:
            for ev in events:
                db.insert_usage(conn, **ev)
            conn.commit()
        except Exception as e:
            print(f"[WARN] usage記録失敗: {e}")
        finally:
            conn.close()
