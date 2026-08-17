#!/usr/bin/env python3
"""セッション7の自己検証：ベクトルDB（Qdrant）の運用。

検査するのは次の4点。
  A/B: 本書の 673 チャンクでは HNSW が作られておらず、ef を振ってもリコールが動かない
  C  : フィルタ付き検索の挙動（事前フィルタと事後フィルタ・候補が枯れる）
  D  : ペイロードインデックスは結果を変えず、作成は冪等
  E/F: 決定的IDによる冪等な索引更新と、エイリアスによる版管理・スナップショット

50,000 件のベンチはここでは回さない（verify-all.sh が重くなるため）。
大規模なリコール曲線は tools/bench_hnsw.py を手で実行して確かめること。

埋め込みモデルを使う A/B/C は SKIP_DENSE=1 で飛ばせる（D/E/F はモデル無しで動く）。
"""

from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.getLogger("transformers").setLevel(logging.ERROR)

from qdrant_client.models import (  # noqa: E402
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    SearchParams,
)

from common import count, drop, point_id, recreate, synth_vectors  # noqa: E402
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_queries  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

COLLECTION = "minato_docs_fixed"
PAYLOAD_TMP = "minato_s07_verify_payload"
POSITIONAL_TMP = "minato_s07_verify_positional"
DETERMINISTIC_TMP = "minato_s07_verify_deterministic"
SWITCH_V1, SWITCH_V2 = "minato_s07_verify_v1", "minato_s07_verify_v2"
SWITCH_ALIAS = "minato_s07_verify_alias"

SKIP_DENSE = os.environ.get("SKIP_DENSE") == "1"
failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


client = DenseIndex("dummy").client
docs = load_docs()
chunks = chunk_all(docs, "fixed", size=400, overlap=80)

# --- A. コレクションの設定を読む ---------------------------------------------
if SKIP_DENSE:
    print("SKIP_DENSE=1 のため、埋め込みモデルを使う検証（A/B/C）は飛ばします。")
else:
    from ragkit.dense import Embedder  # noqa: E402

    idx = DenseIndex(COLLECTION)
    if not client.collection_exists(COLLECTION):
        print("コレクションを作成します（1分程度かかります）")
        idx.build(chunks)
    info = client.get_collection(COLLECTION)

    check("コレクションの点数がチャンク数と一致",
          (info.points_count or 0) == len(chunks), f"{info.points_count} == {len(chunks)}")

    hnsw = info.config.hnsw_config
    check("HNSW の既定値は m=16 / ef_construct=100",
          hnsw.m == 16 and hnsw.ef_construct == 100,
          f"m={hnsw.m} / ef_construct={hnsw.ef_construct}")
    check("full_scan_threshold の既定は 10000（単位は KB）",
          hnsw.full_scan_threshold == 10000, f"{hnsw.full_scan_threshold}")
    check("indexing_threshold の既定は 10000（単位は KB）",
          info.config.optimizer_config.indexing_threshold == 10000,
          f"{info.config.optimizer_config.indexing_threshold}")
    # ここがこの章の出発点。673 チャンクでは HNSW が1本も作られていない
    check("673 チャンクでは HNSW が作られていない（総当たりで探している）",
          (info.indexed_vectors_count or 0) == 0,
          f"indexed_vectors_count={info.indexed_vectors_count}")

    # --- B. ef を振ってもリコールが動かない ----------------------------------
    queries = [q for q in load_queries() if q.type != "unanswerable"][:20]
    vecs = [Embedder.encode_query(q.text).tolist() for q in queries]

    def top_ids(vec, ef: int | None = None, exact: bool = False) -> set:
        res = client.query_points(
            COLLECTION, query=vec, limit=10, search_params=SearchParams(hnsw_ef=ef, exact=exact)
        )
        return {p.id for p in res.points}

    truth = [top_ids(v, exact=True) for v in vecs]
    worst, worst_ef = 1.0, None
    for ef in (4, 8, 16, 32, 64, 128):
        recall = sum(len(top_ids(v, ef=ef) & t) / 10 for v, t in zip(vecs, truth)) / len(vecs)
        if recall < worst:
            worst, worst_ef = recall, ef
    check("ef を 4〜128 に振ってもリコールは 1.000 のまま動かない",
          worst == 1.0, f"最小リコール={worst:.3f}（ef={worst_ef}）")

    # --- C. フィルタ付き検索 --------------------------------------------------
    dist = Counter(d.visibility for d in docs)
    check("コーパスの公開範囲は all 297 / manager 4",
          dist["all"] == 297 and dist["manager"] == 4, f"{dict(sorted(dist.items()))}")

    manager_filter = Filter(
        must=[FieldCondition(key="visibility", match=MatchValue(value="manager"))]
    )
    n_manager = count(client, COLLECTION, count_filter=manager_filter)
    check("manager のチャンクは全体のごく一部",
          0 < n_manager < 20, f"{n_manager} / {info.points_count}")

    query_text = "社内規程の取り扱いについて"
    pre = idx.search(query_text, k=20, filters={"visibility": "manager"})
    check("事前フィルタの結果はすべて visibility=manager",
          len(pre) > 0 and all(h.meta.get("visibility") == "manager" for h in pre),
          f"{len(pre)}件")
    check("k=20 を要求しても母集団の件数しか返らない（候補が枯れる）",
          len(pre) == n_manager, f"要求20 / 取得{len(pre)} / 母集団{n_manager}")
    post = [h for h in idx.search(query_text, k=20) if h.meta.get("visibility") == "manager"]
    check("事後フィルタ（Python で捨てる）は事前フィルタより取りこぼす",
          len(post) < len(pre), f"事後{len(post)} < 事前{len(pre)}")

# --- D. ペイロードインデックス -----------------------------------------------
recreate(client, PAYLOAD_TMP)
pay_vecs = synth_vectors(500)
client.upsert(
    PAYLOAD_TMP,
    points=[
        PointStruct(id=i, vector=v.tolist(),
                    payload={"visibility": "manager" if i < 20 else "all"})
        for i, v in enumerate(pay_vecs)
    ],
    wait=True,
)
qv = synth_vectors(1, seed=99)[0].tolist()
mgr = Filter(must=[FieldCondition(key="visibility", match=MatchValue(value="manager"))])
before_ids = [p.id for p in client.query_points(PAYLOAD_TMP, query=qv, limit=10,
                                                query_filter=mgr).points]
check("ペイロードインデックスが無くてもフィルタは効く",
      len(before_ids) == 10 and all(int(i) < 20 for i in before_ids), f"{len(before_ids)}件")
check("インデックスを作る前は payload_schema が空",
      not (client.get_collection(PAYLOAD_TMP).payload_schema or {}), "")
for _ in range(2):  # 2回作って冪等性を確かめる
    client.create_payload_index(PAYLOAD_TMP, field_name="visibility",
                                field_schema=PayloadSchemaType.KEYWORD, wait=True)
schema = client.get_collection(PAYLOAD_TMP).payload_schema or {}
check("インデックスを作ると payload_schema に載る（2回作っても壊れない）",
      "visibility" in schema, f"{sorted(schema)}")
after_ids = [p.id for p in client.query_points(PAYLOAD_TMP, query=qv, limit=10,
                                               query_filter=mgr).points]
check("ペイロードインデックスの有無で結果は変わらない",
      set(before_ids) == set(after_ids), "上位10件のIDが一致")

# --- E. 冪等な索引更新（点IDの決め方） ---------------------------------------
sub = chunks[:20]
kept = sub[1:]
vec_of = {c.chunk_id: v for c, v in zip(sub, synth_vectors(20))}


def snapshot(collection: str) -> dict:
    out: dict = {}
    offset = None
    while True:
        records, offset = client.scroll(collection, limit=256, offset=offset,
                                        with_payload=True, with_vectors=False)
        out.update({r.id: (r.payload or {}).get("chunk_id") for r in records})
        if offset is None:
            return out


recreate(client, POSITIONAL_TMP)
client.upsert(POSITIONAL_TMP, wait=True, points=[
    PointStruct(id=i, vector=vec_of[c.chunk_id].tolist(), payload={"chunk_id": c.chunk_id})
    for i, c in enumerate(sub)])
before_a = snapshot(POSITIONAL_TMP)
client.upsert(POSITIONAL_TMP, wait=True, points=[
    PointStruct(id=i, vector=vec_of[c.chunk_id].tolist(), payload={"chunk_id": c.chunk_id})
    for i, c in enumerate(kept)])
after_a = snapshot(POSITIONAL_TMP)
moved_a = sum(1 for pid, cid in after_a.items() if before_a.get(pid) != cid)
dups_a = len(after_a) - len(set(after_a.values()))
check("位置ベースのIDは1件減らすと全点の中身がずれる",
      moved_a == 19 and count(client, POSITIONAL_TMP) == 20, f"ずれた点={moved_a} / 20点のまま")
check("位置ベースのIDは同じ chunk_id を2つの点に持たせてしまう",
      dups_a == 1, f"重複={dups_a}件")

recreate(client, DETERMINISTIC_TMP)


def det_points(items):
    return [PointStruct(id=point_id(c.chunk_id), vector=vec_of[c.chunk_id].tolist(),
                        payload={"chunk_id": c.chunk_id}) for c in items]


def sync(items) -> None:
    """欲しい状態にそろえる。何度実行しても同じ結果になる（冪等）。"""
    client.upsert(DETERMINISTIC_TMP, points=det_points(items), wait=True)
    desired = {point_id(c.chunk_id) for c in items}
    orphans = [pid for pid in snapshot(DETERMINISTIC_TMP) if pid not in desired]
    if orphans:
        client.delete(DETERMINISTIC_TMP, points_selector=PointIdsList(points=orphans), wait=True)


check("同じ chunk_id からは常に同じ点IDが出る",
      point_id("DOC-0001#001") == point_id("DOC-0001#001")
      and point_id("DOC-0001#001") != point_id("DOC-0001#002"), "uuid5(chunk_id)")
client.upsert(DETERMINISTIC_TMP, points=det_points(sub), wait=True)
before_b = snapshot(DETERMINISTIC_TMP)
client.upsert(DETERMINISTIC_TMP, points=det_points(kept), wait=True)
after_b = snapshot(DETERMINISTIC_TMP)
moved_b = sum(1 for pid, cid in after_b.items() if before_b.get(pid) != cid)
check("決定的IDなら再投入しても中身がずれない",
      moved_b == 0 and len(after_b) - len(set(after_b.values())) == 0, f"ずれた点={moved_b}")
check("投入しただけでは消えた1件が残る（削除は別に必要）",
      count(client, DETERMINISTIC_TMP) == 20, f"{count(client, DETERMINISTIC_TMP)}点")
sync(kept)
check("差分削除で欲しい状態になる", count(client, DETERMINISTIC_TMP) == 19,
      f"{count(client, DETERMINISTIC_TMP)}点")
sync(kept)
sync(kept)
check("同じ処理を何度実行しても結果が変わらない（冪等）",
      count(client, DETERMINISTIC_TMP) == 19, f"{count(client, DETERMINISTIC_TMP)}点")

# --- F. 版管理（エイリアス）とスナップショット --------------------------------
sw_vecs = synth_vectors(10)
for name, version in ((SWITCH_V1, "v1"), (SWITCH_V2, "v2")):
    recreate(client, name)
    client.upsert(name, wait=True, points=[
        PointStruct(id=i, vector=sw_vecs[i].tolist(), payload={"version": version})
        for i in range(10)])


def switch_alias(target: str) -> None:
    ops = []
    if any(a.alias_name == SWITCH_ALIAS for a in client.get_aliases().aliases):
        ops.append(DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=SWITCH_ALIAS)))
    ops.append(CreateAliasOperation(
        create_alias=CreateAlias(collection_name=target, alias_name=SWITCH_ALIAS)))
    client.update_collection_aliases(change_aliases_operations=ops)


def alias_version() -> str:
    res = client.query_points(SWITCH_ALIAS, query=sw_vecs[0].tolist(), limit=1)
    return (res.points[0].payload or {}).get("version", "?")


switch_alias(SWITCH_V1)
v_before = alias_version()
switch_alias(SWITCH_V2)
v_after = alias_version()
switch_alias(SWITCH_V1)
v_back = alias_version()
check("エイリアスを付け替えると検索先が入れ替わる（切り戻しもできる）",
      (v_before, v_after, v_back) == ("v1", "v2", "v1"), f"{v_before} -> {v_after} -> {v_back}")

try:
    snap = client.create_snapshot(collection_name=SWITCH_V1, wait=True)
    names = [s.name for s in client.list_snapshots(collection_name=SWITCH_V1)]
    check("コレクションのスナップショットを作って一覧に出せる",
          snap is not None and snap.name in names, f"{snap.name if snap else None}")
    client.delete_snapshot(collection_name=SWITCH_V1, snapshot_name=snap.name, wait=True)
except Exception as exc:  # noqa: BLE001
    check("コレクションのスナップショットを作って一覧に出せる", False, f"{type(exc).__name__}: {exc}")

client.update_collection_aliases(change_aliases_operations=[
    DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=SWITCH_ALIAS))])
drop(client, PAYLOAD_TMP, POSITIONAL_TMP, DETERMINISTIC_TMP, SWITCH_V1, SWITCH_V2)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション7の検証はすべて成功しました。")
