#!/usr/bin/env python3
"""本書のコーパス（673 チャンク）で ef を振る（セッション7・第3節）。

結論を先に言うと「何も起きない」。それを自分の目で確かめるためのスクリプト。
小さなコレクションでは Qdrant が HNSW を作らず総当たりで探すため、
ef はそもそも読まれていない。

  docker compose exec app python src/session07/ef_sweep.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.getLogger("transformers").setLevel(logging.ERROR)

from qdrant_client.models import SearchParams  # noqa: E402

from ragkit.corpus import load_queries  # noqa: E402
from ragkit.dense import DenseIndex, Embedder  # noqa: E402

COLLECTION = "minato_docs_fixed"
EF_VALUES = (4, 8, 16, 32, 64, 128)
K = 10
N_QUERIES = 30

idx = DenseIndex(COLLECTION)
if not idx.client.collection_exists(COLLECTION):
    raise SystemExit(
        "minato_docs_fixed がありません。先に `python src/session06/verify.py` を実行してください。"
    )

info = idx.client.get_collection(COLLECTION)
print(
    f"コレクション: {COLLECTION}"
    f"（{info.points_count or 0}点 / インデックス済み {info.indexed_vectors_count or 0}点）"
)

queries = [q for q in load_queries() if q.type != "unanswerable"][:N_QUERIES]
vecs = [Embedder.encode_query(q.text).tolist() for q in queries]


def top_ids(vec, ef: int | None = None, exact: bool = False) -> set:
    res = idx.client.query_points(
        COLLECTION, query=vec, limit=K, search_params=SearchParams(hnsw_ef=ef, exact=exact)
    )
    return {p.id for p in res.points}


truth = [top_ids(v, exact=True) for v in vecs]

print(
    f"クエリ{len(queries)}件で ef を振り、"
    f"総当たり（exact=True）の上位{K}件をどれだけ再現できるかを測ります\n"
)
for ef in EF_VALUES:
    recall, same = 0.0, 0
    for v, t in zip(vecs, truth):
        got = top_ids(v, ef=ef)
        recall += len(got & t) / K
        same += int(got == t)
    print(
        f"  ef={ef:>3} : リコール@10 = {recall / len(vecs):.3f} / "
        f"exact と完全一致したクエリ {same}/{len(vecs)} 件"
    )

print(
    "\nef を 32 倍にしても何も動きません。indexed_vectors_count が 0、つまり HNSW が\n"
    "1本も作られていないため、Qdrant は ef を無視して総当たりで探しています。"
)
