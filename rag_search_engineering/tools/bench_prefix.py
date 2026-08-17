#!/usr/bin/env python3
"""e5 の prefix（`query:` / `passage:`）の効果を検索精度で測る。セッション6の実測値の出典。

重要：prefix の効果は「1組のテキストの類似度」では測れない。
prefix を外した方が類似度の絶対値が高く出ることもあるため、
検索全体の順位（Recall / nDCG）で比較する必要がある。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.dense import VECTOR_SIZE, DenseIndex, Embedder  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.models import Hit  # noqa: E402

K = 10
COLLECTION_NOPREFIX = "minato_docs_noprefix"


class NoPrefixIndex:
    """prefix を付けずに索引と検索を行う比較用の検索器（誤用の再現）。"""

    def __init__(self, chunks) -> None:
        from qdrant_client.models import Distance, PointStruct, VectorParams

        self.idx = DenseIndex(COLLECTION_NOPREFIX)
        client = self.idx.client
        if client.collection_exists(COLLECTION_NOPREFIX):
            client.delete_collection(COLLECTION_NOPREFIX)
        client.create_collection(
            COLLECTION_NOPREFIX,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        model = Embedder.get()
        vecs = model.encode([c.text for c in chunks], batch_size=16,
                            normalize_embeddings=True, show_progress_bar=False)
        points = [
            PointStruct(id=i, vector=v.tolist(),
                        payload={"chunk_id": c.chunk_id, "doc_id": c.doc_id, "text": c.text})
            for i, (c, v) in enumerate(zip(chunks, vecs))
        ]
        for i in range(0, len(points), 128):
            client.upsert(COLLECTION_NOPREFIX, points=points[i : i + 128], wait=True)

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        vec = Embedder.get().encode(query, normalize_embeddings=True,
                                   show_progress_bar=False).tolist()
        res = self.idx.client.query_points(COLLECTION_NOPREFIX, query=vec, limit=k,
                                          with_payload=True)
        return [Hit(p.payload["chunk_id"], p.payload["doc_id"], float(p.score),
                    p.payload["text"], {}) for p in res.points]


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)

    with_prefix = DenseIndex("minato_docs_fixed")
    if not with_prefix.client.collection_exists("minato_docs_fixed"):
        print("prefix あり索引を作成します（1分程度）")
        with_prefix.build(chunks)

    print("prefix なし索引を作成します（1分程度）")
    without = NoPrefixIndex(chunks)

    rep_with = evaluate(with_prefix, queries, qrels, k=K, label="prefix あり（正しい使い方）")
    rep_without = evaluate(without, queries, qrels, k=K, label="prefix なし（誤用）")
    print()
    print(rep_with.summary())
    print(rep_without.summary())

    delta = rep_with.macro["recall"] - rep_without.macro["recall"]
    print(f"\nRecall@{K} の差: {delta:+.3f}")
    print("\n=== クエリ型別 Recall@10 ===")
    types = sorted(rep_with.by_type)
    print(f"{'条件':<26}" + "".join(f"{t:>16}" for t in types))
    for rep in (rep_with, rep_without):
        print(f"{rep.label:<26}" + "".join(
            f"{rep.by_type.get(t, {}).get('recall', 0):>16.3f}" for t in types))

    without.idx.client.delete_collection(COLLECTION_NOPREFIX)


if __name__ == "__main__":
    main()
