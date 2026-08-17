#!/usr/bin/env python3
"""ペイロードインデックスの有無を比べる（セッション7・第7節）。

母集団の件数を自分で決めたいので、ここは合成ベクトルで作る。
確かめるのは速度ではなく「インデックスは結果を変えない」「作成は冪等」の2点。

  docker compose exec app python src/session07/payload_index.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qdrant_client.models import (  # noqa: E402
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
)

from common import drop, recreate, synth_vectors  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

COLLECTION = "minato_s07_payload"
N, N_MANAGER, K = 500, 20, 10

client = DenseIndex("dummy").client
recreate(client, COLLECTION)

vecs = synth_vectors(N)
client.upsert(
    COLLECTION,
    points=[
        PointStruct(
            id=i,
            vector=v.tolist(),
            payload={"visibility": "manager" if i < N_MANAGER else "all"},
        )
        for i, v in enumerate(vecs)
    ],
    wait=True,
)
query_vec = synth_vectors(1, seed=99)[0].tolist()
manager_filter = Filter(must=[FieldCondition(key="visibility", match=MatchValue(value="manager"))])


def schema_line() -> str:
    schema = client.get_collection(COLLECTION).payload_schema or {}
    if not schema:
        return "（なし）"
    return " / ".join(
        f"{k}={getattr(v.data_type, 'value', v.data_type)}" for k, v in sorted(schema.items())
    )


def search_ids() -> list:
    res = client.query_points(COLLECTION, query=query_vec, limit=K, query_filter=manager_filter)
    return [p.id for p in res.points]


print(
    f"合成コレクション {COLLECTION} を作りました"
    f"（{N}点 / visibility=manager は {N_MANAGER}点）"
)

print("\n=== 1. ペイロードインデックスが無い状態 ===")
before = search_ids()
print(f"  ペイロードインデックス : {schema_line()}")
print(f"  visibility=manager でフィルタして{K}件要求 -> {len(before)} 件")

print("\n=== 2. インデックスを作る（2回実行して冪等性も確かめる）===")
for _ in range(2):
    client.create_payload_index(
        COLLECTION, field_name="visibility", field_schema=PayloadSchemaType.KEYWORD, wait=True
    )
after = search_ids()
print(f"  ペイロードインデックス : {schema_line()}")
print(f"  visibility=manager でフィルタして{K}件要求 -> {len(after)} 件")

print("\n=== 3. 判定 ===")
print(f"  [{'OK' if set(before) == set(after) else 'NG'}] "
      f"インデックスの有無で結果は変わらない（上位{K}件のIDが一致）")
print(f"  [{'OK' if 'visibility' in (client.get_collection(COLLECTION).payload_schema or {}) else 'NG'}] "
      "同じインデックスを2回作ってもエラーにならない")

drop(client, COLLECTION)
print("一時コレクションを削除しました")
