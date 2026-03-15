from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod


class MessageCollector(ABC):
    """メッセージ収集の基底クラス。将来 ThreadCollector などに拡張できる。"""

    @abstractmethod
    async def collect(self, conn: sqlite3.Connection, run_id: str) -> int:
        """メッセージを収集して DB に保存し、収集件数を返す。"""
        ...
