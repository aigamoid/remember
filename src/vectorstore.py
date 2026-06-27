"""Qdrant ベクトルDB操作。indexer.py / src/rag/engine.py から使用。

マルチテナント前提: 全ポイントの payload に guild_id を持ち、
検索時は必ず guild_id でフィルタする（他サーバーのデータは見えない）。

ハイブリッド検索（#54）: dense（無名・OpenAI embedding）に加え、語彙一致用の BM25 sparse
ベクトル（名前 `bm25`・Modifier.IDF）を持てる。search に sparse を渡すと dense と sparse を
別々に prefetch して RRF で融合する。sparse を渡さなければ従来どおりの dense-only 検索。
"""

from __future__ import annotations

import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Modifier,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

# BM25 sparse ベクトルの名前（dense は従来どおり無名のまま）。
SPARSE_NAME = "bm25"


def _guild_filter(guild_id: str, channel_id: str | None = None) -> Filter:
    must = [FieldCondition(key="guild_id", match=MatchValue(value=str(guild_id)))]
    if channel_id is not None:
        must.append(
            FieldCondition(key="channel_id", match=MatchValue(value=str(channel_id)))
        )
    return Filter(must=must)


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
        """コレクションが無ければ作成する（冪等）。guild_id にインデックスを張る。

        dense（無名・COSINE）に加え、BM25 sparse ベクトル（Modifier.IDF）を宣言する。
        sparse は点ごとに任意（dense-only の点も同居できる）。
        """
        if not self._client.collection_exists(self.collection):
            self._client.create_collection(
                self.collection,
                vectors_config=VectorParams(
                    size=self.vector_size, distance=Distance.COSINE
                ),
                sparse_vectors_config={
                    SPARSE_NAME: SparseVectorParams(modifier=Modifier.IDF)
                },
            )
            self._client.create_payload_index(
                self.collection, "guild_id", field_schema="keyword"
            )

    def drop_collection(self) -> None:
        if self._client.collection_exists(self.collection):
            self._client.delete_collection(self.collection)

    def delete_by_guild(self, guild_id: str) -> None:
        """1サーバー分の点を全削除する（Bot退出・--clean 時）。"""
        if not self._client.collection_exists(self.collection):
            return
        self._client.delete(
            self.collection, points_selector=_guild_filter(guild_id), wait=True
        )

    def delete_by_channel(self, guild_id: str, channel_id: str) -> None:
        """1チャンネル分の点を削除する（/oracle deny 時）。"""
        if not self._client.collection_exists(self.collection):
            return
        self._client.delete(
            self.collection,
            points_selector=_guild_filter(guild_id, channel_id),
            wait=True,
        )

    def upsert(
        self,
        payloads: list[dict],
        vectors: list[list[float]],
        sparse_vectors: list[tuple[list[int], list[float]]] | None = None,
    ) -> None:
        """チャンクを登録する。chunk_id から決定的に UUID を生成して点IDにするため、
        同じチャンクの再登録は上書きになる（冪等）。

        sparse_vectors（各点の (indices, values)）を渡すと dense と一緒に BM25 sparse を
        格納する（ハイブリッド検索用・#54）。None なら従来どおり dense のみ。
        indices が空の点は sparse を付けない（語が無いチャンク）。
        """
        points = []
        for i, (p, vec) in enumerate(zip(payloads, vectors)):
            if sparse_vectors is not None and sparse_vectors[i][0]:
                indices, values = sparse_vectors[i]
                vector = {
                    "": vec,
                    SPARSE_NAME: SparseVector(indices=indices, values=values),
                }
            else:
                vector = vec
            points.append(
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, p["chunk_id"])),
                    vector=vector,
                    payload=p,
                )
            )
        self._client.upsert(self.collection, points=points, wait=True)

    def search(
        self,
        guild_id: str,
        vector: list[float],
        top_k: int = 10,
        sparse: tuple[list[int], list[float]] | None = None,
        prefetch_k: int | None = None,
    ) -> list[dict]:
        """guild_id でフィルタした類似検索。payload に score を加えた辞書リストを返す。

        sparse（クエリの (indices, values)）を渡すと、dense と sparse を別々に prefetch_k 件
        取得し RRF で融合して top_k 件返す（ハイブリッド・#54）。sparse 未指定（または語が空）
        なら従来どおりの dense-only 検索。
        """
        flt = _guild_filter(guild_id)
        if sparse is not None and sparse[0]:
            pk = prefetch_k or max(top_k, 30)
            res = self._client.query_points(
                self.collection,
                prefetch=[
                    # using=None で無名（デフォルト）dense ベクトルを参照する。
                    Prefetch(query=vector, using=None, limit=pk, filter=flt),
                    Prefetch(
                        query=SparseVector(indices=sparse[0], values=sparse[1]),
                        using=SPARSE_NAME,
                        limit=pk,
                        filter=flt,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
        else:
            res = self._client.query_points(
                self.collection,
                query=vector,
                query_filter=flt,
                limit=top_k,
                with_payload=True,
            )
        return [{**pt.payload, "score": pt.score} for pt in res.points]

    def count(self, guild_id: str | None = None) -> int:
        flt = _guild_filter(guild_id) if guild_id is not None else None
        return self._client.count(
            self.collection, count_filter=flt, exact=True
        ).count
