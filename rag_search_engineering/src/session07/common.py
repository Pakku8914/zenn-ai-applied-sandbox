"""セッション7の共通ヘルパ。

ここで作る合成ベクトルは「件数と挙動」を確かめるためのもので、
リコールの測定には使わない（純粋な乱数ベクトルは 384 次元では互いにほぼ等距離になり、
ANN の最悪ケースになる。リコールを測るときは tools/bench_hnsw.py の
「実際の埋め込みを種に増やしたベクトル」を使うこと）。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
from qdrant_client.models import Distance, VectorParams  # noqa: E402

from ragkit.dense import VECTOR_SIZE  # noqa: E402

# chunk_id から点IDを導くときの名前空間。ここを変えると全点のIDが変わるので固定する
ID_NAMESPACE = uuid.NAMESPACE_URL
ID_PREFIX = "minato://chunk/"


def point_id(chunk_id: str) -> str:
    """chunk_id から決定的に点IDを作る。

    同じ chunk_id なら、いつ・どのプロセスで呼んでも同じ UUID が返る。
    「何番目に処理したか」に依存しないので、差分更新しても点がずれない。
    """
    return str(uuid.uuid5(ID_NAMESPACE, f"{ID_PREFIX}{chunk_id}"))


def synth_vectors(n: int, seed: int = 20260815) -> np.ndarray:
    """決定的な合成ベクトル（正規化済み）。中身に意味は無い。"""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, VECTOR_SIZE)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


def recreate(client, name: str, **kwargs) -> None:
    """一時コレクションを作り直す（既にあれば消してから作る）。"""
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(
        name,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        **kwargs,
    )


def count(client, name: str, count_filter=None) -> int:
    """点数を数える（points_count の反映待ちに左右されないよう exact で数える）。"""
    return client.count(name, count_filter=count_filter, exact=True).count


def drop(client, *names: str) -> None:
    for name in names:
        if client.collection_exists(name):
            client.delete_collection(name)
