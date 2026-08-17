#!/usr/bin/env python3
"""HNSW のパラメータとリコール・検索時間の関係を測る（セッション7の実測値の出典）。

【重要な前提】本書のコーパス（673 チャンク）では近似最近傍探索の効果が測れない。
Qdrant は既定で「一定件数を超えるまで HNSW を作らず総当たりで探す」ため、
小さなコレクションでは ef を何に変えてもリコールが 1.000 のまま動かない。
これ自体がセッション7で最初に伝えるべき事実（小さなデータでパラメータを
チューニングしても何も起きない）である。

そこでこのスクリプトでは、実際のチャンク埋め込みを種にして件数だけを増やした
ベクトル集合（固定シード）で ANN の挙動を測る。文書の内容ではなく「ベクトルの
件数と分布」が効く現象なので、埋め込みの多様体構造を保った合成で再現できる。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from ragkit.dense import VECTOR_SIZE, DenseIndex, Embedder  # noqa: E402

COLLECTION = "minato_hnsw_bench"
EF_VALUES = (4, 8, 16, 32, 64, 128, 256)
K = 10
SEED = 20260815


def make_vectors(n: int, noise: float = 0.02) -> np.ndarray:
    """実際のコーパスの埋め込みを種に、件数だけを増やした集合を作る。

    純粋な乱数ベクトルを使ってはいけない。384 次元の一様乱数は互いにほぼ等距離
    （最近傍と 100 番目の距離差がほとんど無い）になり、ANN にとって最悪ケースになる。
    実測では ef=256 でもリコール 0.28 しか出ず、現実の埋め込みの挙動とかけ離れる。

    そこで実際のチャンク埋め込み 673 件を種にし、2 つの実ベクトルの凸結合に
    小さなノイズを足して増やす。埋め込みが乗っている多様体の構造（話題ごとの
    まとまり）を保ったまま件数を増やせる。
    """
    from ragkit.chunk import chunk_all
    from ragkit.corpus import load_docs

    chunks = chunk_all(load_docs(), "fixed", size=400, overlap=80)
    seed_vecs = np.asarray(Embedder.encode_passages([c.text for c in chunks]), dtype=np.float32)

    rng = np.random.default_rng(SEED)
    i = rng.integers(0, len(seed_vecs), size=n)
    j = rng.integers(0, len(seed_vecs), size=n)
    w = rng.uniform(0.7, 1.0, size=(n, 1)).astype(np.float32)
    vecs = w * seed_vecs[i] + (1 - w) * seed_vecs[j]
    vecs += rng.normal(scale=noise, size=vecs.shape).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs.astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vectors", type=int, default=50_000, help="登録するベクトル数")
    ap.add_argument("--queries", type=int, default=50, help="評価に使うクエリ数")
    ap.add_argument("--m", type=int, default=8)
    ap.add_argument("--ef-construct", type=int, default=32)
    ap.add_argument("--noise", type=float, default=0.02, help="種ベクトルに足すノイズの大きさ")
    args = ap.parse_args()

    from qdrant_client.models import (
        Distance, HnswConfigDiff, OptimizersConfigDiff, PointStruct, SearchParams, VectorParams,
    )

    client = DenseIndex("dummy").client
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        COLLECTION,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        hnsw_config=HnswConfigDiff(m=args.m, ef_construct=args.ef_construct),
        # 既定では一定件数までインデックスを作らない。明示的に 1 にして必ず作らせる
        optimizers_config=OptimizersConfigDiff(indexing_threshold=1),
    )

    vecs = make_vectors(args.vectors, noise=args.noise)
    print(f"ベクトル数={args.vectors:,} 次元={VECTOR_SIZE} m={args.m} "
          f"ef_construct={args.ef_construct} noise={args.noise}")

    t0 = time.perf_counter()
    batch_starts = list(range(0, len(vecs), 1000))
    for i in batch_starts:
        batch = vecs[i : i + 1000]
        client.upsert(
            COLLECTION,
            points=[PointStruct(id=int(i + j), vector=v.tolist(), payload={})
                    for j, v in enumerate(batch)],
            # 最後のバッチだけ完了を待つ（空の upsert は 400 になるので区切りに使えない）
            wait=(i == batch_starts[-1]),
        )
    print(f"登録: {time.perf_counter() - t0:.1f}s")

    # インデックス構築が終わるまで待つ
    t0 = time.perf_counter()
    while True:
        info = client.get_collection(COLLECTION)
        if info.status == "green" and (info.indexed_vectors_count or 0) >= args.vectors * 0.99:
            break
        if time.perf_counter() - t0 > 600:
            print(f"警告: インデックス構築が終わりません（status={info.status}, "
                  f"indexed={info.indexed_vectors_count}）")
            break
        time.sleep(2)
    info = client.get_collection(COLLECTION)
    print(f"インデックス構築: {time.perf_counter() - t0:.1f}s "
          f"(points={info.points_count:,}, indexed={info.indexed_vectors_count:,})\n")

    # クエリと総当たりの正解
    rng = np.random.default_rng(SEED + 1)
    qidx = rng.choice(args.vectors, size=args.queries, replace=False)
    queries = vecs[qidx]
    sims = queries @ vecs.T
    exact = [set(np.argsort(-row)[:K].tolist()) for row in sims]

    print(f"{'ef':>6}{'リコール':>12}{'中央値(ms)':>14}{'p95(ms)':>10}")
    print("-" * 42)
    for ef in EF_VALUES:
        recalls, lat = [], []
        for q, truth in zip(queries, exact):
            t0 = time.perf_counter()
            res = client.query_points(COLLECTION, query=q.tolist(), limit=K,
                                      search_params=SearchParams(hnsw_ef=ef, exact=False))
            lat.append((time.perf_counter() - t0) * 1000)
            got = {int(p.id) for p in res.points}
            recalls.append(len(got & truth) / K)
        lat.sort()
        print(f"{ef:>6}{statistics.mean(recalls):>12.3f}{statistics.median(lat):>14.1f}"
              f"{lat[int(len(lat) * 0.95) - 1]:>10.1f}")

    # 総当たり（exact=True）との比較
    lat = []
    for q in queries:
        t0 = time.perf_counter()
        client.query_points(COLLECTION, query=q.tolist(), limit=K,
                            search_params=SearchParams(exact=True))
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    print(f"{'総当たり':>6}{1.0:>12.3f}{statistics.median(lat):>14.1f}"
          f"{lat[int(len(lat) * 0.95) - 1]:>10.1f}")

    client.delete_collection(COLLECTION)


if __name__ == "__main__":
    main()
