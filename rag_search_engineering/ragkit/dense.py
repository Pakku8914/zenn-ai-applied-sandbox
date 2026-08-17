"""密ベクトル検索（multilingual-e5-small + Qdrant）。セッション6・7の参照実装。

e5 系は非対称検索用に prefix を要求する（クエリ側 "query: " / 文書側 "passage: "）。
prefix を外すと静かに精度が落ちるため、ここで必ず付ける（セッション6の題材）。
"""

from __future__ import annotations

import os
from typing import Iterable

from .models import Chunk, Hit

MODEL_NAME = "intfloat/multilingual-e5-small"
# HuggingFace 側の更新で結果が変わらないよう revision を固定する
MODEL_REVISION = "main"
VECTOR_SIZE = 384


class Embedder:
    """埋め込みモデルの薄いラッパ。プロセス内で1度だけロードする。"""

    _model = None

    @classmethod
    def get(cls):
        if cls._model is None:
            from sentence_transformers import SentenceTransformer

            cls._model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION)
        return cls._model

    @classmethod
    def encode_passages(cls, texts: Iterable[str], batch_size: int = 16):
        return cls.get().encode(
            [f"passage: {t}" for t in texts],
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    @classmethod
    def encode_query(cls, text: str):
        return cls.get().encode(
            f"query: {text}", normalize_embeddings=True, show_progress_bar=False
        )


class DenseIndex:
    """Qdrant のコレクションを1つ管理する検索器。"""

    def __init__(self, collection: str, url: str | None = None) -> None:
        from qdrant_client import QdrantClient

        self.collection = collection
        self.client = QdrantClient(url=url or os.environ.get("QDRANT_URL", "http://qdrant:6333"))

    def build(self, chunks: list[Chunk], batch_size: int = 128, recreate: bool = True) -> "DenseIndex":
        from qdrant_client.models import Distance, PointStruct, VectorParams

        if recreate and self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                # 正規化済みベクトルなので COSINE と DOT はどちらでも同順位になる
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

        vectors = Embedder.encode_passages([c.text for c in chunks])
        points = [
            PointStruct(
                id=i,
                vector=vec.tolist(),
                payload={"chunk_id": c.chunk_id, "doc_id": c.doc_id, "text": c.text, **c.meta},
            )
            for i, (c, vec) in enumerate(zip(chunks, vectors))
        ]
        for i in range(0, len(points), batch_size):
            self.client.upsert(self.collection, points=points[i : i + batch_size], wait=True)
        return self

    def search(self, query: str, k: int = 10, filters: dict | None = None, ef: int | None = None) -> list[Hit]:
        from qdrant_client.models import SearchParams

        vec = Embedder.encode_query(query).tolist()
        res = self.client.query_points(
            self.collection,
            query=vec,
            limit=k,
            query_filter=_to_qdrant_filter(filters),
            search_params=SearchParams(hnsw_ef=ef) if ef else None,
            with_payload=True,
        )
        hits: list[Hit] = []
        for p in res.points:
            payload = p.payload or {}
            hits.append(
                Hit(
                    chunk_id=payload.get("chunk_id", str(p.id)),
                    doc_id=payload.get("doc_id", ""),
                    score=float(p.score),
                    text=payload.get("text", ""),
                    meta={k2: v for k2, v in payload.items() if k2 not in ("chunk_id", "doc_id", "text")},
                )
            )
        return hits


def _to_qdrant_filter(filters: dict | None):
    """{"visibility": ["all", "dept"]} のような辞書を Qdrant の Filter に変換する。"""
    if not filters:
        return None
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

    must = []
    for key, want in filters.items():
        if isinstance(want, (list, tuple, set)):
            must.append(FieldCondition(key=key, match=MatchAny(any=list(want))))
        else:
            must.append(FieldCondition(key=key, match=MatchValue(value=want)))
    return Filter(must=must)
