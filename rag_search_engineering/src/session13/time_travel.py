#!/usr/bin/env python3
"""時点性：有効な版だけを返す（第6節）。

権限と同じで、時点性も「生成側に最新を選ばせる」のではなく検索条件で解く。
規程（policy）49件を一時コレクションに入れ、有効期間をペイロードに持たせて
  (a) is_current の等値フィルタ
  (b) valid_from <= asof < valid_to の範囲フィルタ
の2通りを比べる。ベクトルは合成（決定的）で、見たいのは母集団の絞り込みだけ。

  docker compose exec app python src/session13/time_travel.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qdrant_client.models import PointStruct  # noqa: E402

from common import (  # noqa: E402
    asof_filter,
    build_versions,
    count,
    current_filter,
    drop,
    qdrant_client,
    recreate,
    synth_vectors,
)

COLL = "minato_s13_versions"
TODAY = 20260815

client = qdrant_client()
rows = build_versions()
recreate(client, COLL)
client.upsert(COLL, wait=True, points=[
    PointStruct(id=i, vector=v.tolist(), payload=row)
    for i, (row, v) in enumerate(zip(rows, synth_vectors(len(rows))))
])

print("=== 1. 版の棚卸し ===")
print(f"  規程の総数        : {count(client, COLL)}")
print(f"  失効済み（旧版）   : {sum(1 for r in rows if not r['is_current'])}")
print(f"  現行              : {sum(1 for r in rows if r['is_current'])}")
for r in rows:
    if not r["is_current"]:
        print(f"    旧版 {r['doc_id']} {r['title']}  "
              f"{r['valid_from']} 〜 {r['valid_to']}")

print("\n=== 2. as-of（時点）で絞る ===")
for asof in (TODAY, 20240101):
    n = count(client, COLL, count_filter=asof_filter(asof))
    print(f"  {asof} 時点で有効な規程: {n} 件")

print("\n=== 3. 等値フィルタ（is_current）との比較 ===")
print(f"  is_current=true : {count(client, COLL, count_filter=current_filter())} 件")

# --- フラグの更新漏れを作る ----------------------------------------------------
stale = next(r for r in rows if not r["is_current"])
stale_id = next(i for i, r in enumerate(rows) if r["doc_id"] == stale["doc_id"])
client.set_payload(COLL, payload={"is_current": True}, points=[stale_id], wait=True)
print(f"\n  旧版 {stale['doc_id']} のフラグを立て忘れた状態を作る（is_current=true のまま）")
print(f"  is_current=true          : {count(client, COLL, count_filter=current_filter())} 件"
      "  ← 旧版が1件混ざった")
print(f"  as-of {TODAY} の範囲条件 : "
      f"{count(client, COLL, count_filter=asof_filter(TODAY))} 件  ← 影響を受けない")

print(
    "\n=== 4. 判定 ===\n"
    "  フラグは「書き換えを忘れたら嘘になる」派生データです。\n"
    "  有効期間そのものを持たせて範囲で絞れば、更新漏れの1点が全体を汚しません。\n"
    "  一方でフラグは索引が軽く、条件も1つで済みます。過去時点の再現が要らないなら妥当です。"
)

drop(client, COLL)
print("\n一時コレクションを削除しました。")
