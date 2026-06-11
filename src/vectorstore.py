"""Qdrant ベクトルDB操作。indexer.py / src/rag/engine.py から使用。

マルチテナント前提: 全ポイントの payload に guild_id を持ち、
検索時は必ず guild_id でフィルタする（他サーバーのデータは見えない）。
"""

from __future__ import annotations

import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)


def _guild_filter(guild_id: str) -> Filter:
    return Filter(
        must=[FieldCondition(key="guild_id", match=MatchValue(value=str(guild_id)))]
    )


class VectorStore:
    def __init__(
        self,
        url: str | None = None,
        collection: str = "waiwai_chunks",
        vector_size: int = 1536,
        client: QdrantClient | None = None,
    ) -> None:
        self.collection = collection
        self.vector_size = vector_size
        self._client = client or QdrantClient(url=url)

    def ensure_collection(self) -> None:
        """コレクションが無ければ作成する（冪等）。guild_id にインデックスを張る。"""
        if not self._client.collection_exists(self.collection):
            self._client.create_collection(
                self.collection,
                vectors_config=VectorParams(
                    size=self.vector_size, distance=Distance.COSINE
                ),
            )
            self._client.create_payload_index(
                self.collection, "guild_id", field_schema="keyword"
            )

    def drop_collection(self) -> None:
        if self._client.collection_exists(self.collection):
            self._client.delete_collection(self.collection)

    def upsert(self, payloads: list[dict], vectors: list[list[float]]) -> None:
        """チャンクを登録する。chunk_id から決定的に UUID を生成して点IDにするため、
        同じチャンクの再登録は上書きになる（冪等）。"""
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, p["chunk_id"])),
                vector=vec,
                payload=p,
            )
            for p, vec in zip(payloads, vectors)
        ]
        self._client.upsert(self.collection, points=points, wait=True)

    def search(
        self, guild_id: str, vector: list[float], top_k: int = 10
    ) -> list[dict]:
        """guild_id でフィルタした類似検索。payload に score を加えた辞書リストを返す。"""
        res = self._client.query_points(
            self.collection,
            query=vector,
            query_filter=_guild_filter(guild_id),
            limit=top_k,
            with_payload=True,
        )
        return [{**pt.payload, "score": pt.score} for pt in res.points]

    def count(self, guild_id: str | None = None) -> int:
        flt = _guild_filter(guild_id) if guild_id is not None else None
        return self._client.count(
            self.collection, count_filter=flt, exact=True
        ).count
