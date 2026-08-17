#!/usr/bin/env python3
"""マルチテナントの分離戦略を実物で比べる（第5節・判断基準）。

  方式A: 単一コレクション + ペイロードフィルタ
  方式B: テナント別コレクション
（方式C: テナント別インスタンスはサンドボックスでは起動しない。表で比較する）

一時コレクション（minato_s13_*）だけを触り、最後に必ず削除する。
ベクトルは合成（決定的）で、ここで見たいのは順位ではなく「何が返る母集団に入るか」。

  docker compose exec app python src/session13/tenant_split.py
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

from common import count, drop, qdrant_client, recreate, synth_vectors  # noqa: E402

POOLED = "minato_s13_pooled"
PER_TENANT = {"acme": "minato_s13_tenant_acme", "beta": "minato_s13_tenant_beta"}
TENANTS = ("acme", "beta")
N_PER_TENANT = 10

client = qdrant_client()
vectors = synth_vectors(N_PER_TENANT * len(TENANTS))
probe = synth_vectors(1, seed=777)[0].tolist()


def tenant_filter(tenant: str) -> Filter:
    """テナント条件。文字列を直接受け取らず、必ずこの関数を通す。"""
    if tenant not in TENANTS:
        raise PermissionError(f"未知のテナントです: {tenant!r}")
    return Filter(must=[FieldCondition(key="tenant", match=MatchValue(value=tenant))])


def collection_for(tenant: str) -> str:
    """テナント名からコレクション名を1か所で導く（方式B の急所）。"""
    if tenant not in PER_TENANT:
        raise PermissionError(f"未知のテナントです: {tenant!r}")
    return PER_TENANT[tenant]


# --- 方式A: 単一コレクション + ペイロードフィルタ ------------------------------
recreate(client, POOLED)
points = []
for i, vec in enumerate(vectors):
    tenant = TENANTS[i // N_PER_TENANT]
    points.append(PointStruct(id=i, vector=vec.tolist(),
                              payload={"tenant": tenant, "doc": f"{tenant}-{i:02d}"}))
client.upsert(POOLED, points=points, wait=True)
# テナント項目にはペイロードインデックスを作る（Qdrant にはマルチテナント向けの
# 設定もあるので、規模が出てきたら公式ドキュメントを確認すること）
client.create_payload_index(POOLED, field_name="tenant",
                            field_schema=PayloadSchemaType.KEYWORD, wait=True)

no_filter = client.query_points(POOLED, query=probe, limit=20, with_payload=True).points
filtered = client.query_points(POOLED, query=probe, limit=20,
                               query_filter=tenant_filter("acme"), with_payload=True).points
print("=== 方式A: 単一コレクション + ペイロードフィルタ ===")
print("  コレクション数            : 1")
print(f"  総点数                    : {count(client, POOLED)}")
print(f"  フィルタ無しで返った点     : {len(no_filter)} 件 "
      f"（テナント: {sorted({(p.payload or {}).get('tenant') for p in no_filter})}）")
print(f"  acme のフィルタで返った点  : {len(filtered)} 件 "
      f"（テナント: {sorted({(p.payload or {}).get('tenant') for p in filtered})}）")
print("  → 1行の付け忘れが全テナントの越境になる。フィルタは必ず1か所に閉じ込める")

# --- 方式B: テナント別コレクション --------------------------------------------
print("\n=== 方式B: テナント別コレクション ===")
for i, tenant in enumerate(TENANTS):
    name = collection_for(tenant)
    recreate(client, name)
    chunk = vectors[i * N_PER_TENANT : (i + 1) * N_PER_TENANT]
    client.upsert(name, wait=True, points=[
        PointStruct(id=j, vector=v.tolist(), payload={"tenant": tenant, "doc": f"{tenant}-{j:02d}"})
        for j, v in enumerate(chunk)])

hits_a = client.query_points(collection_for("acme"), query=probe, limit=20,
                             with_payload=True).points
print(f"  コレクション数            : {len(PER_TENANT)}")
print(f"  acme のコレクションの点数  : {count(client, collection_for('acme'))}")
print(f"  フィルタ無しで返った点     : {len(hits_a)} 件 "
      f"（テナント: {sorted({(p.payload or {}).get('tenant') for p in hits_a})}）")
print("  → フィルタを忘れても越境しない。ただし「名前の取り違え」が新しい事故の入り口になる")

try:
    collection_for("acme ")  # 末尾の空白ひとつで別テナント扱い
except PermissionError as exc:
    print(f"  未知のテナント名は拒否する : {exc}")

print("\n=== 判定 ===")
print("  A はコレクション1つで済み運用が軽い。B は分離が強いがコレクション数がテナント数に比例する。")
print("  どちらを選んでも、混入検査（leak_test.py）を回す義務は変わらない。")

drop(client, POOLED, *PER_TENANT.values())
print("\n一時コレクションを削除しました。")
