#!/usr/bin/env python3
"""問題7の解答：追加・更新・削除を含む冪等な索引更新。

同じ引数で2回実行したら、2回目は何も起きない（追加0 / 更新0 / 削除0）ことを目標にする。

  docker compose exec app python src/session07/my_sync.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qdrant_client.models import PointIdsList, PointStruct  # noqa: E402

from common import count, drop, point_id, recreate, synth_vectors  # noqa: E402
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

COLLECTION = "minato_s07_sync"


def content_hash(text: str) -> str:
    """本文が変わったかどうかの判定に使う（変わっていなければ投入しない）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def current_state(client, collection: str) -> dict[str, str]:
    """{点ID: content_hash} を全件読み出す。件数が多くてもページングで回る。"""
    state: dict[str, str] = {}
    offset = None
    while True:
        records, offset = client.scroll(
            collection, limit=256, offset=offset, with_payload=True, with_vectors=False
        )
        state.update({r.id: (r.payload or {}).get("content_hash", "") for r in records})
        if offset is None:
            return state


def sync_collection(client, collection: str, chunks, vectors) -> dict[str, int]:
    """索引を「あるべき状態」にそろえる。何度実行しても結果が変わらない。"""
    current = current_state(client, collection)
    desired = {point_id(c.chunk_id): (c, v) for c, v in zip(chunks, vectors)}

    added = [pid for pid in desired if pid not in current]
    updated = [
        pid
        for pid, (c, _) in desired.items()
        if pid in current and current[pid] != content_hash(c.text)
    ]
    removed = [pid for pid in current if pid not in desired]

    to_upsert = added + updated
    if to_upsert:
        client.upsert(
            collection,
            wait=True,
            points=[
                PointStruct(
                    id=pid,
                    vector=desired[pid][1].tolist(),
                    payload={
                        "chunk_id": desired[pid][0].chunk_id,
                        "doc_id": desired[pid][0].doc_id,
                        "text": desired[pid][0].text,
                        "content_hash": content_hash(desired[pid][0].text),
                        **desired[pid][0].meta,
                    },
                )
                for pid in to_upsert
            ],
        )
    if removed:
        client.delete(collection, points_selector=PointIdsList(points=removed), wait=True)
    return {"added": len(added), "updated": len(updated), "removed": len(removed)}


if __name__ == "__main__":
    client = DenseIndex("dummy").client
    chunks = chunk_all(load_docs(), "fixed", size=400, overlap=80)[:20]
    vecs = synth_vectors(20)  # 確かめたいのはIDの扱いなのでベクトルは合成でよい
    vec_of = {c.chunk_id: v for c, v in zip(chunks, vecs)}

    recreate(client, COLLECTION)
    for label, items in (
        ("(a) 20件で初回", chunks),
        ("(b) 先頭1件を除いた19件", chunks[1:]),
        ("(c) 同じ19件をもう一度", chunks[1:]),
    ):
        r = sync_collection(client, COLLECTION, items, [vec_of[c.chunk_id] for c in items])
        print(
            f"{label} : 追加 {r['added']:>2} / 更新 {r['updated']:>2} / "
            f"削除 {r['removed']:>2} -> {count(client, COLLECTION)} 点"
        )
    drop(client, COLLECTION)
