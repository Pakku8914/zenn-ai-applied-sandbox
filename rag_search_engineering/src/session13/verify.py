#!/usr/bin/env python3
"""セッション13の自己検証：権限とフィルタ検索。

中心は「権限別に全クエリを回して混入0を確認する」テスト（C節）。
それ以外は、その結論を支える前提と、周辺の事故（キャッシュ・時点性・権限変更）の検査。

  A: 権限モデル（fail-closed・空の許可リスト・空の辞書の罠）
  B: コーパスの前提（visibility 分布・判定データに制限文書が入っていないこと）
  C: 混入検査（BM25・全クエリ×権限）★この章の成果物
  D: 権限フィルタは検索の指標を下げない
  E: 漏洩経路（混入したヒットはそのままプロンプトへ流れる）
  F: キャッシュの鍵と無効化
  G: テナント分離（単一コレクション＋フィルタ／コレクション分割）
  H: 時点性（有効期間の範囲条件と派生フラグ）
  I: 権限変更・削除（ペイロード更新・冪等・点IDが動かないこと）
  J: 密ベクトルでの混入検査（SKIP_DENSE=1 で飛ばせる）

一時コレクションは minato_s13_* だけを使い、最後に必ず削除する。
既存の minato_docs_fixed は再利用する（作り直さない）。
"""

from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.getLogger("transformers").setLevel(logging.ERROR)

from qdrant_client.models import (  # noqa: E402
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointIdsList,
    PointStruct,
)

from common import (  # noqa: E402
    AccessAwareRetriever,
    PostFilterRetriever,
    Principal,
    SearchCache,
    all_chunks,
    allowed_visibility,
    asof_filter,
    build_versions,
    count,
    current_filter,
    dense_index,
    drop,
    leak_test_queries,
    leaked_hits,
    lexical_index,
    point_id,
    probe_queries,
    qdrant_client,
    recreate,
    restricted_docs,
    sweep,
    synth_vectors,
    visibility_filter,
    visible_to,
)
from leak_test import run_all  # noqa: E402

from ragkit.answer import build_user_prompt  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402

K = 10
MEMBER = Principal(user_id="u-1001", role="member", dept="営業部")
BOSS = Principal(user_id="u-2001", role="manager", dept="営業部")
SKIP_DENSE = os.environ.get("SKIP_DENSE") == "1"

POOLED_TMP = "minato_s13_verify_pooled"
TENANT_A_TMP = "minato_s13_verify_tenant_a"
TENANT_B_TMP = "minato_s13_verify_tenant_b"
VERSIONS_TMP = "minato_s13_verify_versions"
PERM_TMP = "minato_s13_verify_perm"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


docs = load_docs()
queries = load_queries()
qrels = load_qrels()
index = lexical_index()
probes = probe_queries(docs)
test_queries = leak_test_queries()

# --- A. 権限モデル ------------------------------------------------------------
try:
    allowed_visibility("admin")
    ok_unknown = False
except PermissionError:
    ok_unknown = True
check("未知の役割は拒否する（fail-closed）", ok_unknown, "allowed_visibility('admin') -> PermissionError")
check("member の許可リストは all だけ", allowed_visibility("member") == ("all",),
      f"{allowed_visibility('member')}")
check("manager は all と manager を見てよい", allowed_visibility("manager") == ("all", "manager"),
      f"{allowed_visibility('manager')}")
check("権限フィルタは空の辞書を返さない", visibility_filter(MEMBER) == {"visibility": ["all"]},
      f"{visibility_filter(MEMBER)}")

probe0 = probes[0]
plain_ids = [h.chunk_id for h in index.search(probe0.text, k=K)]
empty_ids = [h.chunk_id for h in index.search(probe0.text, k=K, filters={})]
check("filters={} はフィルタ無しと同じ結果になる（fail-open の罠）", plain_ids == empty_ids,
      f"上位{len(plain_ids)}件が完全一致")

# --- B. コーパスの前提 --------------------------------------------------------
dist = Counter(d.visibility for d in docs)
check("公開範囲は all 297 / manager 4", dist["all"] == 297 and dist["manager"] == 4,
      f"{dict(sorted(dist.items()))}")
check("制限文書は4件で、すべて管理職限定の運用細則",
      len(restricted_docs(docs)) == 4
      and all("管理職限定" in d.title for d in restricted_docs(docs)),
      f"{[d.doc_id for d in restricted_docs(docs)]}")

vis_of = {d.doc_id: d.visibility for d in docs}
relevant_restricted = [
    (qid, doc_id) for qid, row in qrels.items() for doc_id, grade in row.items()
    if grade >= 1 and vis_of.get(doc_id) != "all"
]
check("判定データ（qrels）に制限文書は1件も含まれない", not relevant_restricted,
      f"適合とされた制限文書 {len(relevant_restricted)} 件")
check("プローブクエリは制限文書の数だけ作られる", len(probes) == 4,
      f"{[p.text for p in probes]}")
check("検査クエリは業務クエリ120件＋プローブ4件", len(test_queries) == len(queries) + 4,
      f"{len(test_queries)} 件")

# --- C. 混入検査（この章の成果物）---------------------------------------------
print("\n--- 権限別・全クエリの混入検査（bm25）---")
results = run_all(index, "bm25", test_queries, k=K)
for r in results:
    print("   " + r.line())

by_label = {r.label: r for r in results}
unfiltered = by_label["bm25 フィルタ無し(member基準)"]
post = by_label["bm25 事後フィルタ(member)"]
pre_member = by_label["bm25 事前フィルタ(member)"]
pre_boss = by_label["bm25 事前フィルタ(manager)"]

check("フィルタ無しでは一般社員に制限文書が混入する（漏洩の再現）",
      unfiltered.n_leaked_hits >= 1,
      f"混入クエリ {unfiltered.n_leaked_queries} 件 / 混入ヒット {unfiltered.n_leaked_hits} 件")
check("事前フィルタ（member）は全クエリで混入0", pre_member.clean,
      f"{pre_member.n_queries} クエリ / 混入 {pre_member.n_leaked_hits} 件")
check("事前フィルタ（manager）も許可外の混入0", pre_boss.clean,
      f"{pre_boss.n_queries} クエリ / 混入 {pre_boss.n_leaked_hits} 件")
check("事後フィルタも混入は0（混入0だけでは実装の良否を判定できない）", post.clean,
      f"混入 {post.n_leaked_hits} 件")
check("manager ロールでは制限文書が取れる（落としすぎていない）",
      any(h.meta.get("visibility") == "manager"
          for p in probes
          for h in AccessAwareRetriever(index, BOSS).search(p.text, k=K)),
      "プローブで manager チャンクが返る")

leaky = [p for p in probes if leaked_hits(index.search(p.text, k=K), MEMBER)]
check("プローブクエリで漏洩を再現できる", len(leaky) >= 1,
      f"{len(leaky)}/4 件のプローブで混入")

if leaky:
    n_pre = len(AccessAwareRetriever(index, MEMBER).search(leaky[0].text, k=K))
    n_post = len(PostFilterRetriever(index, MEMBER).search(leaky[0].text, k=K))
    check("事後フィルタは同じクエリで結果が痩せる（取りこぼし）", n_post < n_pre,
          f"{leaky[0].query_id}: 事後 {n_post} 件 < 事前 {n_pre} 件")

# --- D. 権限フィルタは検索の指標を下げない ------------------------------------
base = evaluate(index, queries, qrels, k=K, label="bm25 / フィルタ無し")
filtered = evaluate(index, queries, qrels, k=K, label="bm25 / member(権限フィルタ)",
                    filters=visibility_filter(MEMBER))
print(f"\n   {base.summary()}")
print(f"   {filtered.summary()}")
drops = [
    qid for qid, row in base.per_query.items()
    if filtered.per_query[qid]["recall"] < row["recall"] - 1e-9
]
check("権限フィルタで Recall@10 が下がるクエリは1件も無い", not drops,
      f"下がったクエリ {len(drops)} 件（判定データに制限文書が無いため原理的に下がらない）")
check("基準の Recall@10 は 0.763（セッション5の実測と一致）",
      abs(base.macro["recall"] - 0.763) < 0.005, f"{base.macro['recall']:.3f}")

# --- E. 漏洩経路 --------------------------------------------------------------
if leaky:
    bad_hits = leaked_hits(index.search(leaky[0].text, k=K), MEMBER)
    prompt = build_user_prompt(leaky[0].text, bad_hits, max_chars=2000)
    check("混入したヒットはそのまま生成プロンプトに載る",
          "人事評価の参考情報" in prompt and bad_hits[0].chunk_id in prompt,
          f"{len(prompt)} 文字のプロンプトに制限文書の本文と chunk_id が含まれる")

# --- F. キャッシュ ------------------------------------------------------------
print()
shared = (leaky or probes)[0].text
cache_results: dict[str, int] = {}
for mode in ("query_only", "principal", "user"):
    cache = SearchCache(mode)
    cache.get_or_search(AccessAwareRetriever(index, BOSS), BOSS, shared, k=K)
    hits = cache.get_or_search(AccessAwareRetriever(index, MEMBER), MEMBER, shared, k=K)
    cache_results[mode] = len(leaked_hits(hits, MEMBER))
check("キャッシュキーに権限が無いと、上司の結果が一般社員へ配られる",
      cache_results["query_only"] >= 1, f"混入 {cache_results['query_only']} 件")
check("キャッシュキーに権限スコープを入れれば混入0",
      cache_results["principal"] == 0 and cache_results["user"] == 0,
      f"principal={cache_results['principal']} / user={cache_results['user']}")

cache = SearchCache("principal")
victim_doc = next(h.doc_id for h in index.search(shared, k=K) if h.meta.get("visibility") == "all")
cache.get_or_search(AccessAwareRetriever(index, MEMBER), MEMBER, shared, k=K)
saved = {cid: index.chunks[cid] for cid in index.chunks if index.chunks[cid].doc_id == victim_doc}
for cid, chunk in saved.items():
    index.chunks[cid] = replace(chunk, meta={**chunk.meta, "visibility": "manager"})
try:
    stale = cache.get_or_search(AccessAwareRetriever(index, MEMBER), MEMBER, shared, k=K)
    check("索引を直してもキャッシュを消さないと古い結果が返り続ける",
          any(h.doc_id == victim_doc for h in stale), f"{victim_doc} が残っている")
    dropped = cache.invalidate_doc(victim_doc)
    fresh = cache.get_or_search(AccessAwareRetriever(index, MEMBER), MEMBER, shared, k=K)
    check("キャッシュを無効化すると秘匿化が効く",
          dropped >= 1 and not any(h.doc_id == victim_doc for h in fresh),
          f"{dropped} 件のエントリを破棄")
finally:
    for cid, chunk in saved.items():
        index.chunks[cid] = chunk
check("検査のあと索引のメタデータは元に戻っている",
      all(index.chunks[cid].meta.get("visibility") == "all" for cid in saved), f"{len(saved)} 件")

# --- G. テナント分離 ----------------------------------------------------------
client = qdrant_client()
recreate(client, POOLED_TMP)
tenants = ("acme", "beta")
vecs = synth_vectors(20)
client.upsert(POOLED_TMP, wait=True, points=[
    PointStruct(id=i, vector=v.tolist(), payload={"tenant": tenants[i // 10]})
    for i, v in enumerate(vecs)])
probe_vec = synth_vectors(1, seed=777)[0].tolist()


def tenants_in(points) -> set:
    return {(p.payload or {}).get("tenant") for p in points}


no_filter = client.query_points(POOLED_TMP, query=probe_vec, limit=20, with_payload=True).points
acme_filter = Filter(must=[FieldCondition(key="tenant", match=MatchValue(value="acme"))])
only_acme = client.query_points(POOLED_TMP, query=probe_vec, limit=20,
                                query_filter=acme_filter, with_payload=True).points
check("単一コレクションはフィルタを忘れると越境する", tenants_in(no_filter) == set(tenants),
      f"{sorted(tenants_in(no_filter))}")
check("テナントフィルタを付ければ越境しない", tenants_in(only_acme) == {"acme"},
      f"{len(only_acme)} 件すべて acme")

for name, tenant in ((TENANT_A_TMP, "acme"), (TENANT_B_TMP, "beta")):
    recreate(client, name)
    client.upsert(name, wait=True, points=[
        PointStruct(id=i, vector=v.tolist(), payload={"tenant": tenant})
        for i, v in enumerate(synth_vectors(10, seed=1 if tenant == "acme" else 2))])
split_hits = client.query_points(TENANT_A_TMP, query=probe_vec, limit=20, with_payload=True).points
check("コレクションを分ければフィルタ無しでも越境しない", tenants_in(split_hits) == {"acme"},
      f"{len(split_hits)} 件すべて acme")

# --- H. 時点性 ----------------------------------------------------------------
rows = build_versions()
recreate(client, VERSIONS_TMP)
client.upsert(VERSIONS_TMP, wait=True, points=[
    PointStruct(id=i, vector=v.tolist(), payload=row)
    for i, (row, v) in enumerate(zip(rows, synth_vectors(len(rows))))])
n_old = sum(1 for r in rows if not r["is_current"])
check("規程は49件・うち旧版は6件（更新日 2023-04-01 の6件）",
      len(rows) == 49 and n_old == 6, f"policy {len(rows)} 件 / 旧版 {n_old} 件")
check("as-of 2026-08-15 で有効な規程は 49 − 6 = 43 件",
      count(client, VERSIONS_TMP, count_filter=asof_filter(20260815)) == 43,
      f"{count(client, VERSIONS_TMP, count_filter=asof_filter(20260815))} 件")
check("as-of 2024-01-01 では旧版6件だけが有効",
      count(client, VERSIONS_TMP, count_filter=asof_filter(20240101)) == 6,
      f"{count(client, VERSIONS_TMP, count_filter=asof_filter(20240101))} 件")
check("派生フラグ is_current の件数は範囲条件と一致する（更新漏れが無い間は）",
      count(client, VERSIONS_TMP, count_filter=current_filter()) == 43, "43 件")

stale_row = next(r for r in rows if not r["is_current"])
stale_id = next(i for i, r in enumerate(rows) if r["doc_id"] == stale_row["doc_id"])
client.set_payload(VERSIONS_TMP, payload={"is_current": True}, points=[stale_id], wait=True)
check("フラグの更新漏れは等値フィルタを汚す",
      count(client, VERSIONS_TMP, count_filter=current_filter()) == 44, "44 件（旧版が1件混ざる）")
check("有効期間の範囲条件は更新漏れの影響を受けない",
      count(client, VERSIONS_TMP, count_filter=asof_filter(20260815)) == 43, "43 件のまま")

# --- I. 権限変更・削除 --------------------------------------------------------
restricted_ids = {d.doc_id for d in restricted_docs(docs)}
chunks = [c for c in all_chunks() if c.doc_id in restricted_ids]
public_chunks = [c for c in all_chunks() if c.doc_id not in restricted_ids][:20]
chunks += public_chunks
recreate(client, PERM_TMP)
client.upsert(PERM_TMP, wait=True, points=[
    PointStruct(id=point_id(c.chunk_id), vector=v.tolist(),
                payload={"chunk_id": c.chunk_id, "doc_id": c.doc_id,
                         "visibility": c.meta["visibility"]})
    for c, v in zip(chunks, synth_vectors(len(chunks)))])

n_all_before = count(client, PERM_TMP, count_filter=visible_to("member"))
check("初期状態では一般公開のチャンクだけが member に見える",
      n_all_before == len(public_chunks)
      and count(client, PERM_TMP, count_filter=visible_to("manager")) == len(chunks),
      f"member {n_all_before} / manager {len(chunks)}")

target_doc = public_chunks[0].doc_id
target_ids = [point_id(c.chunk_id) for c in chunks if c.doc_id == target_doc]
ids_before = {r.id for r in client.scroll(PERM_TMP, limit=256, with_payload=False)[0]}
client.set_payload(PERM_TMP, payload={"visibility": "manager"}, points=target_ids, wait=True)
n_after = count(client, PERM_TMP, count_filter=visible_to("member"))
ids_after = {r.id for r in client.scroll(PERM_TMP, limit=256, with_payload=False)[0]}
check("秘匿化（all -> manager）はペイロード更新だけで即座に効く",
      n_after == n_all_before - len(target_ids), f"{n_all_before} -> {n_after}")
check("点IDも総点数も変わらない（再埋め込み不要）",
      ids_before == ids_after and count(client, PERM_TMP) == len(chunks),
      f"{len(chunks)} 点のまま")
client.set_payload(PERM_TMP, payload={"visibility": "manager"}, points=target_ids, wait=True)
check("同じ更新を2回実行しても結果が変わらない（冪等）",
      count(client, PERM_TMP, count_filter=visible_to("member")) == n_after, f"{n_after} 件")

client.delete(PERM_TMP, points_selector=PointIdsList(points=target_ids), wait=True)
gone = count(client, PERM_TMP, count_filter=Filter(
    must=[FieldCondition(key="doc_id", match=MatchAny(any=[target_doc]))]))
check("削除要求は点の削除で反映される", gone == 0 and count(client, PERM_TMP) == len(chunks) - len(target_ids),
      f"{target_doc} の残り {gone} 点 / 総点数 {count(client, PERM_TMP)}")

drop(client, POOLED_TMP, TENANT_A_TMP, TENANT_B_TMP, VERSIONS_TMP, PERM_TMP)

# --- J. 密ベクトルでの混入検査 -------------------------------------------------
if SKIP_DENSE:
    print("\nSKIP_DENSE=1 のため、密ベクトルの検証（J）は飛ばします。")
else:
    print("\n--- 権限別・全クエリの混入検査（dense）---")
    dense = dense_index()
    pre = sweep(lambda q, kk: AccessAwareRetriever(dense, MEMBER).search(q, k=kk),
                MEMBER, test_queries, K, label="dense 事前フィルタ(member)")
    print("   " + pre.line())
    check("密ベクトルでも事前フィルタなら全クエリで混入0", pre.clean,
          f"{pre.n_queries} クエリ / 混入 {pre.n_leaked_hits} 件")

    dense_leaky = [p for p in probes if leaked_hits(dense.search(p.text, k=K), MEMBER)]
    check("密ベクトルでもフィルタ無しなら混入する", len(dense_leaky) >= 1,
          f"{len(dense_leaky)}/4 件のプローブで混入")

    manager_hits = dense.search("社内規程の取り扱いについて", k=20, filters={"visibility": "manager"})
    check("事前フィルタの母集団は manager チャンク4件（セッション7の実測と一致）",
          len(manager_hits) == 4
          and all(h.meta.get("visibility") == "manager" for h in manager_hits),
          f"{len(manager_hits)} 件")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション13の検証はすべて成功しました。")
