#!/usr/bin/env python3
"""コレクションの版管理（セッション7・第9節）。

新方式を「別のコレクションとして並行構築し、エイリアスを付け替える」。
作り直しではなく付け替えなので、切り替えは一瞬で、切り戻しも一瞬。

  docker compose exec app python src/session07/collection_switch.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qdrant_client.models import (  # noqa: E402
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    PointStruct,
)

from common import count, drop, recreate, synth_vectors  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

V1, V2 = "minato_s07_switch_v1", "minato_s07_switch_v2"
ALIAS = "minato_s07_switch"
N = 50

client = DenseIndex("dummy").client
vecs = synth_vectors(N)


def build(name: str, version: str) -> None:
    recreate(client, name)
    client.upsert(
        name,
        points=[
            PointStruct(id=i, vector=vecs[i].tolist(), payload={"version": version})
            for i in range(N)
        ],
        wait=True,
    )


def alias_exists() -> bool:
    return any(a.alias_name == ALIAS for a in client.get_aliases().aliases)


def switch_alias(target: str) -> None:
    """エイリアスを target に向ける。削除と作成を1リクエストで送るので原子的に入れ替わる。"""
    ops = []
    if alias_exists():
        ops.append(DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=ALIAS)))
    ops.append(
        CreateAliasOperation(create_alias=CreateAlias(collection_name=target, alias_name=ALIAS))
    )
    client.update_collection_aliases(change_aliases_operations=ops)
    print(f"  {ALIAS} -> {target}")


def current_version() -> str:
    """エイリアス名で検索して、いまどちらのコレクションを見ているかを確かめる。"""
    res = client.query_points(ALIAS, query=vecs[0].tolist(), limit=1)
    return (res.points[0].payload or {}).get("version", "?")


print("=== 1. 現行（v1）を用意し、エイリアスを向ける ===")
build(V1, "v1")
print(f"  {V1} : {count(client, V1)} 点")
switch_alias(V1)
print(f"  エイリアス経由の検索が見ているのは : {current_version()}")

print("\n=== 2. 新方式（v2）を並行構築する。検索は止まらない ===")
build(V2, "v2")
print(f"  {V2} : {count(client, V2)} 点")
print(f"  エイリアス経由の検索が見ているのは : {current_version()}")

print("\n=== 3. 比較が済んだら切り替える（1リクエストで原子的に入れ替わる）===")
switch_alias(V2)
print(f"  エイリアス経由の検索が見ているのは : {current_version()}")

print("\n=== 4. 切り戻し（v1 を消していないので一瞬で戻せる）===")
switch_alias(V1)
print(f"  エイリアス経由の検索が見ているのは : {current_version()}")

client.update_collection_aliases(
    change_aliases_operations=[DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=ALIAS))]
)
drop(client, V1, V2)
print("一時コレクションとエイリアスを削除しました")
