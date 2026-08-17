#!/usr/bin/env python3
"""索引側とクエリ側の prefix を独立に切り替えて評価する（セッション6・問題7）。

  A 索引あり × クエリあり : e5 の正しい使い方（Recall@10 0.783）
  B 索引なし × クエリなし : 両方付け忘れ（Recall@10 0.761）
  C 索引あり × クエリなし : 片側だけ
  D 索引なし × クエリあり : 片側だけ

C・D の値は本書の実測値表に無い。測って設計メモに記録すること。
作業用コレクションは条件ごとに作り直し、最後に必ず削除する。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qdrant_client.models import Distance, PointStruct, VectorParams  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.dense import VECTOR_SIZE, DenseIndex, Embedder  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.models import Hit  # noqa: E402

WORK_COLLECTION = "tmp_s06_prefix"  # 本番の minato_docs_* は絶対に使わない
CONDITIONS = {  # ラベル: (索引側に passage: を付けるか, クエリ側に query: を付けるか)
    "A 索引あり × クエリあり": (True, True),
    "B 索引なし × クエリなし": (False, False),
    "C 索引あり × クエリなし": (True, False),
    "D 索引なし × クエリあり": (False, True),
}


class PrefixIndex:
    """prefix の付け方を索引側・クエリ側で独立に指定できる検索器。"""

    def __init__(self, name: str, chunks, passage_prefix: bool, query_prefix: bool) -> None:
        self.collection = name
        self.query_prefix = query_prefix
        self.idx = DenseIndex(name)
        client = self.idx.client
        if client.collection_exists(name):
            client.delete_collection(name)
        client.create_collection(
            name, vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE))

        texts = [c.text for c in chunks]
        vecs = (Embedder.encode_passages(texts) if passage_prefix
                else Embedder.get().encode(texts, batch_size=16,
                                           normalize_embeddings=True, show_progress_bar=False))
        points = [PointStruct(id=i, vector=v.tolist(),
                              payload={"chunk_id": c.chunk_id, "doc_id": c.doc_id,
                                       "text": c.text})
                  for i, (c, v) in enumerate(zip(chunks, vecs))]
        for i in range(0, len(points), 128):
            client.upsert(name, points=points[i:i + 128], wait=True)

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        vec = (Embedder.encode_query(query) if self.query_prefix
               else Embedder.get().encode(query, normalize_embeddings=True,
                                          show_progress_bar=False))
        res = self.idx.client.query_points(self.collection, query=vec.tolist(),
                                           limit=k, with_payload=True)
        return [Hit(p.payload["chunk_id"], p.payload["doc_id"], float(p.score),
                    p.payload["text"], {}) for p in res.points]

    def drop(self) -> None:
        self.idx.client.delete_collection(self.collection)


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    for label, (passage_prefix, query_prefix) in CONDITIONS.items():
        idx = PrefixIndex(WORK_COLLECTION, chunks, passage_prefix, query_prefix)
        try:
            rep = evaluate(idx, queries, qrels, k=10, label=label)
            print(f"{rep.summary()}  abbrev={rep.by_type['abbrev']['recall']:.3f}")
        finally:
            idx.drop()  # 条件ごとに必ず片付ける


if __name__ == "__main__":
    main()
