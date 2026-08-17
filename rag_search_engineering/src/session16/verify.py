#!/usr/bin/env python3
"""セッション16の自己検証：インデックスの運用。

検査するのは次の9点。

  A: 差分検出（追加・更新・削除）と、更新日だけに頼ったときの見落とし
  B: 冪等な同期（2回目は何も起きない）と dry-run の一致
  C: 孤児チャンクの再現と掃除
  D: 並行構築・追いつき・エイリアスの切り替えと切り戻し
  E: 切り替えの合格判定（レイテンシ予算で判定が変わる）
  F: 鮮度（文書の古さ／索引の遅れ／SLO 達成率）
  G: A/B の割り当てと、少数サンプルの確率
  H: コスト試算
  I: OpenSearch のエイリアス切り替え（起動していれば。無ければスキップ）

埋め込みモデルは使わないので数秒で終わる。一時コレクションは minato_s16_* で作り、
最後に必ず削除する（minato_docs_fixed には触らない）。
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alias_compare  # noqa: E402
import cost_model  # noqa: E402
import gate  # noqa: E402
from common import (  # noqa: E402
    ASOF,
    bucket,
    count,
    diff_by_updated_at,
    diff_docs,
    doc_chunk_ids,
    doc_state,
    drop,
    drop_alias,
    find_text,
    index_state,
    lag_days,
    make_doc,
    percentile,
    recreate,
    switch_alias,
    sync,
    tail_prob,
    vector_for,
)
from freshness import RUN1, indexed_at_batch, indexed_at_daily, slo_rate  # noqa: E402
from incremental import LAST_RUN, build_versions  # noqa: E402
from orphan import OBSOLETE  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.getLogger("transformers").setLevel(logging.ERROR)

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_queries  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

INC = "minato_s16_verify_incremental"
ORPH = "minato_s16_verify_orphan"
SW1, SW2 = "minato_s16_verify_v1", "minato_s16_verify_v2"
SW_ALIAS = "minato_s16_verify_alias"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def fixed(docs):
    return chunk_all(docs, "fixed", size=400, overlap=80)


def heading(docs):
    return chunk_all(docs, "heading", max_chars=600)


client = DenseIndex("dummy").client

# --- A. 差分検出 ---------------------------------------------------------------
previous, current, stale, ids = build_versions()
diff = diff_docs(doc_state(previous), current)
check("差分は 追加1・更新1・削除1・変更なし18",
      diff.counts() == {"added": 1, "changed": 1, "removed": 1, "unchanged": 18},
      f"{diff.counts()}")

by_date = diff_by_updated_at(current, LAST_RUN)
check("更新日で拾えるのは追加と更新の2件だけ（削除は原理的に出てこない）",
      set(by_date) == {ids["added"], ids["changed"]}, f"{sorted(by_date)}")

by_date_stale = diff_by_updated_at(stale, LAST_RUN)
check("改訂日を直し忘れた更新は、更新日方式では見落とす",
      set(by_date_stale) == {ids["added"]}
      and diff_docs(doc_state(previous), stale).counts()["changed"] == 1,
      f"更新日={sorted(by_date_stale)} / 内容ハッシュ=1件")

# --- B. 冪等な同期 -------------------------------------------------------------
recreate(client, INC)
prev_chunks = fixed(previous)
s1 = sync(client, INC, prev_chunks, indexed_at=LAST_RUN)
check("初回は全チャンクを投入する",
      s1.upserted == len(prev_chunks) and s1.deleted == 0
      and count(client, INC) == len(prev_chunks),
      f"{s1.line()} / 点数={count(client, INC)}")

s2 = sync(client, INC, prev_chunks, indexed_at=LAST_RUN)
check("2回目は1件も投入しない（冪等）",
      s2.upserted == 0 and s2.deleted == 0 and s2.unchanged == len(prev_chunks),
      s2.line())

cur_chunks = fixed(current)
n_before = count(client, INC)
plan = sync(client, INC, cur_chunks, dry_run=True)
check("dry-run は索引を変えない", count(client, INC) == n_before, f"点数={n_before}")
check("dry-run が投入と削除の予定を出す",
      plan.upserted > 0 and len(plan.orphans) > 0 and plan.deleted == 0, plan.line())

s3 = sync(client, INC, cur_chunks, indexed_at="2026-08-16")
check("実行結果は dry-run の計画と一致する",
      s3.upserted == plan.upserted and s3.deleted == len(plan.orphans)
      and s3.orphans == plan.orphans, f"計画 {plan.line()} / 実行 {s3.line()}")
check("削除した文書の点は残っていない",
      not doc_chunk_ids(client, INC, ids["removed"]), ids["removed"])
check("追加した文書の点が入っている",
      bool(doc_chunk_ids(client, INC, ids["added"])), ids["added"])

state_after = index_state(client, INC)
touched = {cid for cid, i in state_after.items() if i["indexed_at"] == "2026-08-16"}
expected = {ids["changed"], ids["added"]}
check("触ったのは更新・追加した文書の点だけ",
      bool(touched) and all(state_after[cid]["doc_id"] in expected for cid in touched),
      f"再投入 {len(touched)} 点")

s4 = sync(client, INC, cur_chunks, indexed_at="2026-08-16")
check("もう一度流しても何も起きない（冪等）",
      s4.upserted == 0 and s4.deleted == 0, s4.line())

# --- C. 孤児チャンク -----------------------------------------------------------
old_a = make_doc("DOC-S16A", 1000, updated_at="2026-05-20", tail=OBSOLETE)
doc_b = make_doc("DOC-S16B", 600, updated_at="2026-05-20")
new_a = make_doc("DOC-S16A", 400, updated_at="2026-08-16")


def small(docs):
    return chunk_all(docs, "fixed", size=200, overlap=0)


check("長さからチャンク数が決まる（1000字=5 / 600字=3 / 400字=2）",
      (len(small([old_a])), len(small([doc_b])), len(small([new_a]))) == (5, 3, 2),
      f"{(len(small([old_a])), len(small([doc_b])), len(small([new_a])))}")

recreate(client, ORPH)
sync(client, ORPH, small([old_a, doc_b]), indexed_at="2026-05-20")
check("改訂前は8点", count(client, ORPH) == 8, f"{count(client, ORPH)}")

bad = sync(client, ORPH, small([new_a, doc_b]), indexed_at="2026-08-16", prune=False)
check("孤児が3件あるのに、投入は1件も発生しない（何も起きていないように見える）",
      len(bad.orphans) == 3 and bad.upserted == 0 and bad.unchanged == 5, bad.line())
check("掃除しないと点数が減らない",
      count(client, ORPH) == 8 and len(doc_chunk_ids(client, ORPH, "DOC-S16A")) == 5,
      f"点数={count(client, ORPH)} / DOC-S16A={len(doc_chunk_ids(client, ORPH, 'DOC-S16A'))}")
check("廃止した一文が索引に残っている",
      find_text(client, ORPH, OBSOLETE) == ["DOC-S16A#005"],
      f"{find_text(client, ORPH, OBSOLETE)}")

good = sync(client, ORPH, small([new_a, doc_b]), indexed_at="2026-08-16")
check("孤児を掃除すると欲しい状態になる",
      good.deleted == 3 and count(client, ORPH) == 5
      and len(doc_chunk_ids(client, ORPH, "DOC-S16A")) == 2, good.line())
check("廃止した一文は検索できなくなった",
      find_text(client, ORPH, OBSOLETE) == [], "0件")

again = sync(client, ORPH, small([new_a, doc_b]), indexed_at="2026-08-16")
check("掃除も冪等（2回目は何も起きない）",
      again.upserted == 0 and again.deleted == 0 and count(client, ORPH) == 5, again.line())

# --- D. 並行構築と切り替え -----------------------------------------------------
docs20 = load_docs()[:20]
updated = replace(docs20[2], body=docs20[2].body + "\n2026-08-16 改訂：受付時間を変更します。",
                  updated_at="2026-08-16")
docs_now = [updated if d.doc_id == updated.doc_id else d for d in docs20]


def caught_up(collection: str) -> list[str]:
    """並行構築中の更新が届いている点（更新した文書のもの）を返す。"""
    return [cid for cid, i in index_state(client, collection).items()
            if i["doc_id"] == updated.doc_id and i["indexed_at"] == "2026-08-16"]


recreate(client, SW1)
recreate(client, SW2)
sync(client, SW1, fixed(docs20), indexed_at="2026-08-15")
sync(client, SW2, heading(docs20), indexed_at="2026-08-15")
check("新旧が別のコレクションとして同時に存在する",
      count(client, SW1) > 0 and count(client, SW2) > count(client, SW1),
      f"v1={count(client, SW1)} / v2={count(client, SW2)}")

c1 = sync(client, SW1, fixed(docs_now), indexed_at="2026-08-16")
check("片方にだけ流すと、新方式の索引は古いまま",
      c1.upserted >= 1 and bool(caught_up(SW1)) and not caught_up(SW2),
      f"v1={len(caught_up(SW1))} 点 / v2={len(caught_up(SW2))} 点")
c2 = sync(client, SW2, heading(docs_now), indexed_at="2026-08-16")
check("両系統に流せば追いつく（並行構築中の更新も反映される）",
      c2.upserted >= 1 and bool(caught_up(SW2)), f"v2={len(caught_up(SW2))} 点")

check("引き渡し前の点検：孤児が残っていない",
      not sync(client, SW1, fixed(docs_now), dry_run=True).orphans
      and not sync(client, SW2, heading(docs_now), dry_run=True).orphans, "両系統とも0")


def method_via_alias() -> str:
    res = client.query_points(SW_ALIAS, query=vector_for("プローブ").tolist(), limit=1,
                              with_payload=True)
    return (res.points[0].payload or {}).get("method", "?")


switch_alias(client, SW_ALIAS, SW1)
before = method_via_alias()
switch_alias(client, SW_ALIAS, SW2)
after = method_via_alias()
switch_alias(client, SW_ALIAS, SW1)
back = method_via_alias()
check("エイリアスの付け替えで検索先が入れ替わり、切り戻せる",
      (before, after, back) == ("fixed", "heading", "fixed"), f"{before} -> {after} -> {back}")

# --- E. 合格判定 ---------------------------------------------------------------
r500 = gate.run(500.0)
r2000 = gate.run(2000.0)
check("候補A（チャンク方式の変更）は精度で落ちる",
      r500[0]["delta"] == -0.036 and not r500[0]["accuracy_ok"], f"{r500[0]['delta']:+.3f}")
check("レイテンシ予算 500ms では合格する候補が無い",
      not any(r["passed"] for r in r500) and gate.adopt(r500) is None, "採用なし")
check("予算 2000ms なら2件が合格し、精度が高い候補Bを採用する",
      sum(1 for r in r2000 if r["passed"]) == 2 and (gate.adopt(r2000) or "").startswith("候補B"),
      f"{gate.adopt(r2000)}")

# --- F. 鮮度 -------------------------------------------------------------------
docs = load_docs()
ages = [lag_days(d.updated_at, ASOF) for d in docs]
check("文書の古さ：中央値 97 日 / p95 167 日 / 最大 1232 日",
      (percentile(ages, 0.5), percentile(ages, 0.95), max(ages)) == (97, 167, 1232),
      f"{(percentile(ages, 0.5), percentile(ages, 0.95), max(ages))}")
check("当日更新 36 件 / 1年以上前 6 件",
      sum(1 for a in ages if a == 0) == 36 and sum(1 for a in ages if a >= 365) == 6,
      f"{sum(1 for a in ages if a == 0)} / {sum(1 for a in ages if a >= 365)}")

target = [d for d in docs if d.updated_at > RUN1]
check("初回構築で載るのが 229 件、その後の更新が 72 件",
      len(docs) - len(target) == 229 and len(target) == 72, f"{len(docs) - len(target)} / {len(target)}")
lags = [lag_days(d.updated_at, indexed_at_batch(d.updated_at)) for d in target]
check("バッチ2回の運用では遅れが 88 日と 1 日に割れる",
      dict(Counter(lags)) == {88: 36, 1: 36}, f"{dict(sorted(Counter(lags).items()))}")
check("7日以内の SLO 達成率は 50.0%", slo_rate(lags) == 50.0, f"{slo_rate(lags)}%")
daily = [lag_days(d.updated_at, indexed_at_daily(d.updated_at)) for d in target]
check("日次バッチにすれば遅れは最大1日・達成率 100.0%",
      max(daily) == 1 and slo_rate(daily) == 100.0, f"{slo_rate(daily)}%")

# --- G. A/B --------------------------------------------------------------------
queries = [q for q in load_queries() if q.type != "unanswerable"]
arms = Counter(bucket(q.query_id) for q in queries)
check("110 クエリの割り当ては両群に散る（ちょうど半々にはならない）",
      arms["A"] + arms["B"] == 110 and 40 <= arms["A"] <= 70, f"A={arms['A']} / B={arms['B']}")
check("同じキーは何度引いても同じ群",
      all(bucket(q.query_id) == bucket(q.query_id) for q in queries), "決定的")
changed = sum(1 for q in queries if bucket(q.query_id) != bucket(q.query_id, salt="s16-2"))
check("salt を変えると割り当てを引き直せる", 0 < changed < 110, f"{changed} 件が入れ替わる")
canary = sum(1 for q in queries if bucket(q.query_id, ratio=1) == "B")
check("1% のカナリアはごく少数にしか当たらない", canary <= 8, f"{canary} 件")
check("互角でも 10 回中 7 勝以上する確率は 0.171875",
      abs(tail_prob(10, 7) - 0.171875) < 1e-12, f"{tail_prob(10, 7)}")
check("互角でも 20 回中 15 勝以上する確率は 0.020695",
      round(tail_prob(20, 15), 6) == 0.020695, f"{tail_prob(20, 15):.6f}")

# --- H. コスト -----------------------------------------------------------------
cost = cost_model.summary()
check("ベクトル1本は 1,536 バイト / 673 チャンクで 1,009.5 KB",
      cost["vec_bytes"] == 1536 and cost["book_vec_kb"] == 1009.5,
      f"{cost['vec_bytes']} / {cost['book_vec_kb']}")
check("HNSW のしきい値に届くのは約 6,666 チャンクから",
      cost["threshold_chunks"] == 6666, f"{cost['threshold_chunks']}")
check("10万チャンクのベクトルは 146.5 MiB・並行構築中は 293.0 MiB",
      cost["target_vec_mib"] == 146.5 and cost["peak_vec_mib"] == 293.0,
      f"{cost['target_vec_mib']} / {cost['peak_vec_mib']}")
check("全再索引 94.6 分に対し、日次1%の増分は 56.8 秒（100.0 倍の差）",
      (cost["full_minutes"], cost["daily_seconds"], cost["ratio"]) == (94.6, 56.8, 100.0),
      f"{cost['full_minutes']} 分 / {cost['daily_seconds']} 秒")
check("ベクトルは本文のペイロードより重い（容量の主役はベクトル）",
      300_000 < cost["text_bytes"] < 1_500_000 and cost["text_ratio"] < 1.0,
      f"{cost['text_bytes']:,} バイト（ベクトルの {cost['text_ratio']} 倍）")

# --- I. OpenSearch（任意） -----------------------------------------------------
if alias_compare.is_available():
    for label, ok in alias_compare.run_switch():
        check(f"[OpenSearch] {label}", ok)
else:
    print("SKIP OpenSearch は起動していないので、エイリアスの比較は飛ばします "
          "（docker compose --profile search-engine up -d で有効になります）")

# --- 後片付け -----------------------------------------------------------------
drop_alias(client, SW_ALIAS)
drop(client, INC, ORPH, SW1, SW2)
leftovers = [c.name for c in client.get_collections().collections
             if c.name.startswith("minato_s16")]
check("一時コレクションを残していない", not leftovers, f"{leftovers}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション16の検証はすべて成功しました。")
