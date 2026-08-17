#!/usr/bin/env python3
"""権限変更・文書移動・削除要求を安全に索引へ反映する（第8節）。

  - 公開範囲の変更は「ベクトルを作り直す」作業ではない。ペイロードだけ更新すれば足りる
  - 点IDが chunk_id から決まっている（セッション7の uuid5）ので、更新しても点がずれない
  - 厳しくする変更（秘匿化・削除）は、索引の更新とキャッシュの無効化が終わるまで完了しない

一時コレクション（minato_s13_perm）だけを触り、最後に必ず削除する。

  docker compose exec app python src/session13/perm_change.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qdrant_client.models import (  # noqa: E402
    FieldCondition,
    Filter,
    MatchAny,
    PointIdsList,
    PointStruct,
)

from common import (  # noqa: E402
    all_chunks,
    count,
    drop,
    point_id,
    qdrant_client,
    recreate,
    restricted_docs,
    synth_vectors,
    visible_to,
)

COLL = "minato_s13_perm"

client = qdrant_client()

# 制限文書4件ぶんのチャンク + 一般公開のチャンク20件を入れる
restricted_ids = {d.doc_id for d in restricted_docs()}
chunks = [c for c in all_chunks() if c.doc_id in restricted_ids]
public = [c for c in all_chunks() if c.doc_id not in restricted_ids][:20]
chunks += public

recreate(client, COLL)
client.upsert(COLL, wait=True, points=[
    PointStruct(id=point_id(c.chunk_id), vector=v.tolist(),
                payload={"chunk_id": c.chunk_id, "doc_id": c.doc_id,
                         "visibility": c.meta["visibility"], "title": c.meta["title"]})
    for c, v in zip(chunks, synth_vectors(len(chunks)))
])


def snapshot() -> dict:
    out: dict = {}
    offset = None
    while True:
        records, offset = client.scroll(COLL, limit=256, offset=offset, with_payload=True)
        out.update({r.id: (r.payload or {}).get("visibility") for r in records})
        if offset is None:
            return out


def ids_of(doc_id: str) -> list[str]:
    return [point_id(c.chunk_id) for c in chunks if c.doc_id == doc_id]


print("=== 1. 初期状態 ===")
print(f"  総点数            : {count(client, COLL)}")
print(f"  member から見える : {count(client, COLL, count_filter=visible_to('member'))}")
print(f"  manager から見える: {count(client, COLL, count_filter=visible_to('manager'))}")

# --- 2. 秘匿化（all -> manager）------------------------------------------------
target = public[0].doc_id
targets = ids_of(target)
before = snapshot()
client.set_payload(COLL, payload={"visibility": "manager"}, points=targets, wait=True)
after = snapshot()
print(f"\n=== 2. 秘匿化：{target} を all -> manager ===")
print(f"  更新した点        : {len(targets)}")
print(f"  member から見える : {count(client, COLL, count_filter=visible_to('member'))}")
print(f"  点IDは変わったか   : {set(before) != set(after)}  ← 変わらない（uuid5(chunk_id) 由来）")
print(f"  総点数            : {count(client, COLL)}  ← 再埋め込みも再投入も不要")

# 2回実行しても同じ状態（冪等）
client.set_payload(COLL, payload={"visibility": "manager"}, points=targets, wait=True)
print(f"  同じ更新を2回実行 : member から見える点は "
      f"{count(client, COLL, count_filter=visible_to('member'))} 件のまま（冪等）")

# --- 3. 公開（manager -> all）-------------------------------------------------
opened = sorted(restricted_ids)[0]
client.set_payload(COLL, payload={"visibility": "all"}, points=ids_of(opened), wait=True)
print(f"\n=== 3. 公開：{opened} を manager -> all ===")
print(f"  member から見える : {count(client, COLL, count_filter=visible_to('member'))}")
print("  緩める変更は遅れても事故になりません。急ぐのは常に厳しくする側です。")

# --- 4. 削除要求 ---------------------------------------------------------------
doomed = ids_of(target)
client.delete(COLL, points_selector=PointIdsList(points=doomed), wait=True)
print(f"\n=== 4. 削除要求：{target} を索引から消す ===")
print(f"  総点数            : {count(client, COLL)}")
print(f"  残っている点      : "
      f"{count(client, COLL, count_filter=Filter(must=[FieldCondition(key='doc_id', match=MatchAny(any=[target]))]))} 件")
print(
    "  索引から消えても、キャッシュ・ログ・バックアップ・スナップショットには残ります。\n"
    "  削除要求は『どこまで消したか』の一覧を持たないと完了を宣言できません。"
)

drop(client, COLL)
print("\n一時コレクションを削除しました。")
