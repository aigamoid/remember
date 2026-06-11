from __future__ import annotations

from abc import ABC, abstractmethod

import psycopg


class MessageCollector(ABC):
    """メッセージ収集の基底クラス。将来 ThreadCollector などに拡張できる。"""

    @abstractmethod
    async def collect(
        self,
        conn: psycopg.Connection,
        run_id: str,
        channels: list | None = None,
    ) -> int:
        """メッセージを収集して DB に保存し、収集件数を返す。

        channels を指定した場合はそのチャンネルのみ収集する（ワーカーの opt-in 用）。
        """
        ...
