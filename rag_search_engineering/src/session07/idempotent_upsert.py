#!/usr/bin/env python3
"""索引更新を冪等にする（セッション7・第8節）。

点ID の決め方だけで、差分更新の安全性がまるごと変わることを比べる。
ベクトルの中身はここでは関係ないので合成を使う（埋め込みモデルは要らない）。

  docker compose exec app python src/session07/idempotent_upsert.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qdrant_client.models import PointIdsList, PointStruct  # noqa: E402

from common import count, drop, point_id, recreate, synth_vectors  # noqa: E402
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

POSITIONAL = "minato_s07_ids_positional"
DETERMINISTIC = "minato_s07_ids_deterministic"
N = 20

client = DenseIndex("dummy").client
chunks = chunk_all(load_docs(), "fixed", size=400, overlap=80)[:N]
vecs = synth_vectors(N)
vec_of = {c.chunk_id: vecs[i] for i, c in enumerate(chunks)}
kept = chunks[1:]  # 先頭の1件が削除された想定


def snapshot(collection: str) -> dict:
    """{点ID: chunk_id} を全件読み出す。"""
    out: dict = {}
    offset = None
    while True:
        records, offset = client.scroll(
            collection, limit=256, offset=offset, with_payload=True, with_vectors=False
        )
        out.update({r.id: (r.payload or {}).get("chunk_id") for r in records})
        if offset is None:
            return out


def report(before: dict, after: dict) -> tuple[int, int]:
    moved = sum(1 for pid, cid in after.items() if before.get(pid) != cid)
    dups = len(after) - len(set(after.values()))
    return moved, dups


print(
    f"先頭 {N} チャンクを使って、索引更新の冪等性を比べます"
    "（ベクトルの中身は問わないので合成です）"
)

# --- A. 位置ベースのID：enumerate の i をそのまま点IDにする -------------------
recreate(client, POSITIONAL)


def positional_points(items) -> list[PointStruct]:
    return [
        PointStruct(id=i, vector=vec_of[c.chunk_id].tolist(), payload={"chunk_id": c.chunk_id})
        for i, c in enumerate(items)
    ]


client.upsert(POSITIONAL, points=positional_points(chunks), wait=True)
before_a = snapshot(POSITIONAL)
print("\n=== A. 位置ベースのID（enumerate の i をそのまま点IDにする）===")
print(f"  1回目 upsert                      : {count(client, POSITIONAL)} 点")
client.upsert(POSITIONAL, points=positional_points(kept), wait=True)
after_a = snapshot(POSITIONAL)
moved_a, dups_a = report(before_a, after_a)
print(f"  1件減らして {len(kept)} 件を再投入          : {count(client, POSITIONAL)} 点")
print(f"  1回目と中身が変わった点            : {moved_a} 点")
print(f"  同じ chunk_id が2つの点に入った件数 : {dups_a} 件")

# --- B. 決定的ID：chunk_id から uuid5 で導く ---------------------------------
recreate(client, DETERMINISTIC)


def deterministic_points(items) -> list[PointStruct]:
    return [
        PointStruct(
            id=point_id(c.chunk_id),
            vector=vec_of[c.chunk_id].tolist(),
            payload={"chunk_id": c.chunk_id},
        )
        for c in items
    ]


def sync(items) -> None:
    """欲しい状態にそろえる（投入 → 余分な点を差分で削除）。何度実行しても同じ結果になる。"""
    client.upsert(DETERMINISTIC, points=deterministic_points(items), wait=True)
    desired = {point_id(c.chunk_id) for c in items}
    orphans = [pid for pid in snapshot(DETERMINISTIC) if pid not in desired]
    if orphans:
        client.delete(DETERMINISTIC, points_selector=PointIdsList(points=orphans), wait=True)


client.upsert(DETERMINISTIC, points=deterministic_points(chunks), wait=True)
before_b = snapshot(DETERMINISTIC)
print("\n=== B. 決定的ID（uuid5 で chunk_id から導く）===")
print(f"  1回目 upsert                      : {count(client, DETERMINISTIC)} 点")
client.upsert(DETERMINISTIC, points=deterministic_points(kept), wait=True)
after_b = snapshot(DETERMINISTIC)
moved_b, dups_b = report(before_b, after_b)
print(f"  1件減らして {len(kept)} 件を再投入          : {count(client, DETERMINISTIC)} 点")
print(f"  1回目と中身が変わった点            : {moved_b} 点")
print(f"  同じ chunk_id が2つの点に入った件数 : {dups_b} 件")
sync(kept)
print(f"  要らない点を差分で削除             : {count(client, DETERMINISTIC)} 点")
sync(kept)
print(f"  同じ処理をもう一度実行             : {count(client, DETERMINISTIC)} 点")

drop(client, POSITIONAL, DETERMINISTIC)
print("一時コレクションを削除しました")
