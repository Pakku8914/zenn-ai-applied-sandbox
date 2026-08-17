#!/usr/bin/env python3
"""横断復習04（セッション13〜17・間隔反復で2〜12も）の自己検証。

  1. 権限は検索層で止まり、124件の検査で混入が0であること（S13 × S05 × S03 × S07）
  2. キャッシュ鍵に権限スコープを入れないと他人の結果が返ること（S13 × S12 × S16）
  3. 索引側とクエリ側を同じ規則で分割して初めてコードが引けること（S15 × S05）
  4. GraphRAG の導入判断が数字で閉じること（S14 × S02）
  5. 索引運用の算数（検出・孤児・切り替え・鮮度・容量）が合うこと（S16 × S07 × S03）
  6. 本番ログの還流と重み付けで、同じ検索器が別の数字に見えること（S17 × S02 × S12）

APIキー・埋め込みモデル・リランカ・Qdrant を使わない（BM25 と算数だけで回る）。
期待値と一致しなければ非0で終了する。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from access_guard import (  # noqa: E402
    LEAK_PATHS, AccessAwareRetriever, PostFilterRetriever, Principal, allowed_visibility,
    check_queries, leaked_hits, lexical_index, point_id, probe_queries, restricted_docs,
    ScopedCache, sweep, visibility_filter,
)
from decide_lab import (  # noqa: E402
    UNMEASURED, alternatives_tie, binom_tail_ge, cross_theme_share, edge_type_total,
    edges_lost_by_title_change, luck_probability, verdict, wasted_edges,
)
from ident_lab import (  # noqa: E402
    TYPE_PIPELINE, literal_search, search, split_identifier,
)
from ops_math import (  # noqa: E402
    COST_ORDER, ORPHAN_CAUSES, RUNBOOK, diff_by_updated_at, diff_state, embed_minutes,
    embed_seconds, max_lag_days, meets_slo, monthly_full_hours,
    monthly_incremental_minutes, per_chunk_ms, switch_for, vector_bytes, vector_kb,
    vector_mib, vector_share,
)
from reflow_math import (  # noqa: E402
    DIRTY_QUERY, EVAL_SETS, TRAFFIC_ROWS, allocate_min_then_even, allocate_proportional,
    answerable_size, dropped_fields, hash_value, mask_text, min_detectable_rate, pii_hits,
    weighted_recall, zero_hit_rate,
)

from ragkit.corpus import load_docs  # noqa: E402
from ragkit.tokenize_ja import tokenize  # noqa: E402

failures: list[str] = []


def check(label: str, got, want, tol: float = 0.0) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    shown = f"{got:.4f}" if isinstance(want, float) else got
    print(f"[{'OK' if ok else 'NG'}] {label}: got={shown} want={want}")
    if not ok:
        failures.append(label)


def check_true(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'NG'}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


# ---------------------------------------------------------------------------
# 1. 権限を検索層で止める — S13 × S05 × S03 × S07
# ---------------------------------------------------------------------------
print("--- 1. 権限を検索層で止める ---")

docs = load_docs()
member = Principal("u-1043", "member", "経理部")
manager = Principal("u-2001", "manager", "経理部")

check("文書数", len(docs), 301)
check("制限文書（visibility が all ではない文書）", len(restricted_docs(docs)), 4)
check("検査クエリ（業務120件＋プローブ）", len(check_queries()), 124)
check("プローブクエリ", len(probe_queries(docs)), 4)

check("member の許可リスト", allowed_visibility("member"), ("all",))
check("manager の許可リスト", allowed_visibility("manager"), ("all", "manager"))
try:
    allowed_visibility("admin")
    check_true("未知の役割は止める（fail-closed）", False, "例外が出なかった")
except PermissionError:
    check_true("未知の役割は止める（fail-closed）", True)
check("フィルタ辞書は空にならない", visibility_filter(member), {"visibility": ["all"]})

check("漏洩経路の数", len(LEAK_PATHS), 6)
check("生成側の指示で塞げる可能性がある経路の数", sum(1 for _, _, b in LEAK_PATHS if b), 1)

index = lexical_index()
queries = check_queries()
no_filter = sweep(index.search, member, queries, k=10, label="フィルタ無し")
post = sweep(PostFilterRetriever(index, member).search, member, queries, k=10, label="事後")
pre_member = sweep(AccessAwareRetriever(index, member).search, member, queries, k=10,
                   label="事前(member)")
pre_manager = sweep(AccessAwareRetriever(index, manager).search, manager, queries, k=10,
                    label="事前(manager)")
for res in (no_filter, post, pre_member, pre_manager):
    print("      " + res.line())

check("事前フィルタ(member) の混入ヒット", pre_member.n_leaked_hits, 0)
check("事前フィルタ(manager) の混入ヒット", pre_manager.n_leaked_hits, 0)
check("事後フィルタ(member) の混入ヒット", post.n_leaked_hits, 0)
check_true("フィルタを付け忘れると混入する", no_filter.n_leaked_hits > 0,
           f"{no_filter.n_leaked_hits} 件")
check_true("事後フィルタは混入しない代わりに取りこぼす",
           post.n_short >= 1 and post.n_hits < pre_member.n_hits,
           f"ヒット合計 事前 {pre_member.n_hits} > 事後 {post.n_hits} / "
           f"k未満 {post.n_short} 件")

# ---------------------------------------------------------------------------
# 2. 鍵に入れ忘れたものが事故になる — S13 × S12 × S16
# ---------------------------------------------------------------------------
print("\n--- 2. キャッシュ鍵と権限スコープ ---")

probe = probe_queries(docs)[0].text
manager_ret = AccessAwareRetriever(index, manager)
member_ret = AccessAwareRetriever(index, member)
manager_hits = manager_ret.search(probe, k=10)
check_true("プローブクエリは管理職限定の文書を引く",
           any(h.meta.get("visibility") == "manager" for h in manager_hits),
           f"「{probe}」で {len(manager_hits)} 件")

cache_q = ScopedCache("query_only")
first = cache_q.get_or_search(manager_ret, manager, probe)
second = cache_q.get_or_search(member_ret, member, probe)
check_true("クエリ本文だけを鍵にすると2人目に1人目の結果が返る",
           second == first and cache_q.hit_count == 1)
check_true("その結果は一般社員にとって混入である", len(leaked_hits(second, member)) > 0,
           f"{len(leaked_hits(second, member))} 件")

cache_p = ScopedCache("principal")
cache_p.get_or_search(manager_ret, manager, probe)
scoped = cache_p.get_or_search(member_ret, member, probe)
check_true("権限スコープを鍵に入れれば混入しない",
           leaked_hits(scoped, member) == [] and cache_p.hit_count == 0)
other_member = Principal("u-1099", "member", "総務部")
cache_p.get_or_search(member_ret, other_member, probe)
check_true("見える範囲が同じ人どうしはキャッシュを共有できる", cache_p.hit_count == 1)

target = restricted_docs(docs)[0]
check_true("権限変更で捨てるキャッシュが特定できる",
           cache_p.invalidate_doc(target.doc_id) >= 1)
chunk_id = f"{target.doc_id}#001"
check_true("権限を変えても chunk_id は変わらないので点IDも変わらない",
           point_id(chunk_id) == point_id(chunk_id) and len(point_id(chunk_id)) == 36,
           point_id(chunk_id))

# ---------------------------------------------------------------------------
# 3. 索引側とクエリ側を同じ規則で分割する — S15 × S05
# ---------------------------------------------------------------------------
print("\n--- 3. コードの検索 ---")

check("split_identifier('buildIncidentReport')", split_identifier("buildIncidentReport"),
      ["build", "incident", "report"])
check("split_identifier('build_incident_report')", split_identifier("build_incident_report"),
      ["build", "incident", "report"])
check("先に小文字化すると境界が消える", split_identifier("buildincidentreport"),
      ["buildincidentreport"])
check("split_identifier('MFA_reset')", split_identifier("MFA_reset"), ["mfa", "reset"])
check("split_identifier('HTTPServerError')", split_identifier("HTTPServerError"),
      ["http", "server", "error"])

both = search("buildIncidentReport")
check_true("両側を分割すれば呼び方の違いを吸収できる",
           len(both) == 1 and both[0][1] == "build_incident_report",
           f"{both}")
check("クエリ側を分割しないと0件", search("buildIncidentReport", query_split=False), [])
check("索引側を分割しないと0件", search("buildIncidentReport", index_split=False), [])
check("完全一致は部分語より重い（find_asset）", search("find_asset")[0][0], 5.0, 1e-9)
check("部分語だけで当たる（report）", search("report")[0], (1.0, "build_incident_report"))
check("記号はトークン検索では引けない", search("=="), [])
check("記号は逐次一致でだけ引ける", literal_search("=="), ["find_asset"])
check("tokenize('==', 'morph')", tokenize("==", "morph"), ["=="])
check_true("find_asset は形態素解析の語彙に1語としては残らない",
           "find_asset" not in tokenize("find_asset", "morph"),
           f"{tokenize('find_asset', 'morph')}")
check("型別パイプラインの行数", len(TYPE_PIPELINE), 4)

# ---------------------------------------------------------------------------
# 4. 流行の道具は測ってから入れる — S14 × S02
# ---------------------------------------------------------------------------
print("\n--- 4. GraphRAG の導入判断 ---")

check("エッジ型の内訳の合計", edge_type_total(), 375)
check("主題をまたぐエッジの割合（%）", round(cross_theme_share() * 100, 1), 0.8)
check("同じ主題の中に引いたエッジ", wasted_edges(), 372)
check("タイトルを1件変えるだけで消えるエッジ", edges_lost_by_title_change(), 3)
check_true("グラフと代替案（参照追跡）は同点", alternatives_tie())
check("当てずっぽうでも 3/3 に届く確率", luck_probability(), 0.125, 1e-9)
check("互角の検索器が10問中7勝以上する確率", binom_tail_ge(10, 7), 0.171875, 1e-9)
check("互角の検索器が20問中15勝以上する確率", binom_tail_ge(20, 15), 0.020695, 1e-6)
decision, reasons = verdict()
check_true("判断は『入れない』で、根拠がすべて数字にひもづく",
           decision.startswith("入れない") and len(reasons) >= 4)
check_true("測っていない欄が残っている", len(UNMEASURED) >= 4)

# ---------------------------------------------------------------------------
# 5. 索引の運用 — S16 × S07 × S03
# ---------------------------------------------------------------------------
print("\n--- 5. 索引の運用 ---")

previous = {"DOC-0001": "h1", "DOC-0002": "h2", "DOC-0003": "h3"}
current = {"DOC-0001": "h1", "DOC-0002": "h2x", "DOC-0004": "h4"}
updated_at = {"DOC-0001": "2026-05-10", "DOC-0002": "2026-05-10", "DOC-0004": "2026-08-15"}
d = diff_state(previous, current)
check("指紋で取ると更新が見える", d["changed"], ["DOC-0002"])
check("指紋で取ると削除が見える", d["removed"], ["DOC-0003"])
check("更新日で取ると、更新も削除も落ちる", diff_by_updated_at(updated_at, "2026-08-01"),
      ["DOC-0004"])

check("ベクトル1本のバイト数", vector_bytes(), 1536)
check("673 チャンクのベクトル容量（KB）", vector_kb(673), 1009.5, 0.05)
check("100,000 チャンクのベクトル容量（MiB）", round(vector_mib(100_000), 1), 146.5)
check("1チャンクの埋め込み（ms）", round(per_chunk_ms(), 1), 56.8)
check("全再索引 100,000 チャンク（分）", round(embed_minutes(100_000), 1), 94.6)
check("日次1%の増分 1,000 チャンク（秒）", round(embed_seconds(1_000), 1), 56.8)
check("増分だけを1か月（分）", round(monthly_incremental_minutes(), 1), 28.4)
check("毎日全再索引を1か月（時間）", round(monthly_full_hours(), 1), 47.3)
check_true("容量の主役はベクトル", vector_share() > 0.6, f"{vector_share() * 100:.1f}%")
check("容量を削る順番の先頭", COST_ORDER[0][0], "次元削減")

check("チャンク方式の変更で選ぶ方式", switch_for("チャンク方式・チャンクサイズの変更"),
      "並行構築＋切り替え")
check_true("権限の変更は増分更新（点IDを変えない）",
           switch_for("権限（visibility）の変更").startswith("増分更新"))
try:
    switch_for("よく分からない変更")
    check_true("表に無い変更を勝手に決めない", False, "例外が出なかった")
except KeyError:
    check_true("表に無い変更を勝手に決めない", True)
check("孤児チャンクが生まれる経路", len(ORPHAN_CAUSES), 3)
check("切り替え runbook の段数", len(RUNBOOK), 4)
check_true("鮮度は索引の速さではなくバッチ間隔で決まる",
           max_lag_days(7) == 7 and meets_slo(1) and not meets_slo(30))

# ---------------------------------------------------------------------------
# 6. ログから評価への還流 — S17 × S02 × S12
# ---------------------------------------------------------------------------
print("\n--- 6. ログから評価への還流 ---")

check("ゼロヒット率（%）", round(zero_hit_rate() * 100, 1), 2.3)
masked = mask_text(DIRTY_QUERY)
check("マスクの結果", masked, "<EMAIL> の立替金 <PHONE> <EMPLOYEE_ID>")
check("マスク前に当たる PII", pii_hits(DIRTY_QUERY), ["email", "phone", "employee_id"])
check_true("マスクは冪等で、かけたあとに PII が残らない",
           mask_text(masked) == masked and pii_hits(masked) == [])
check("落とすフィールド", dropped_fields(), ("answer_text", "raw_ip", "user_agent"))
check_true("同じ値は同じハッシュ・ソルトが変われば別のハッシュ",
           hash_value("u-1043", "2026-08-15") == hash_value("u-1043", "2026-08-15")
           and hash_value("u-1043", "2026-08-15") != hash_value("u-1043", "2026-08-16"))

prop = allocate_proportional(20, TRAFFIC_ROWS)
mte = allocate_min_then_even(20, TRAFFIC_ROWS)
check("比例配分（20件）", prop, {"natural": 16, "keyword": 1, "abbrev": 1,
                               "multi_condition": 1, "temporal": 1, "unanswerable": 0})
check("最低2件を保証（20件）", mte, {"natural": 4, "keyword": 4, "abbrev": 3,
                                   "multi_condition": 3, "temporal": 3, "unanswerable": 3})
check_true("比例配分だと少数派の型が入らない", prop["abbrev"] < mte["abbrev"])

expected = {"最初の評価セット(66)": 0.968, "比例配分で還流(69)": 0.948,
            "最低件数を保証して還流(78)": 0.914, "型を均等に見る(120)": 0.763,
            "本番の需要で重み付け(429)": 0.914}
for label, want in expected.items():
    check(f"{label} の Recall@10", weighted_recall(EVAL_SETS[label]), want, 0.001)
check_true("型を均等に見る 0.763 が最も厳しく、最初の評価セット 0.968 が最も甘い",
           weighted_recall(EVAL_SETS["型を均等に見る(120)"])
           < weighted_recall(EVAL_SETS["最低件数を保証して還流(78)"])
           < weighted_recall(EVAL_SETS["比例配分で還流(69)"])
           < weighted_recall(EVAL_SETS["最初の評価セット(66)"]))
check("78件のうち Recall を定義できる件数",
      answerable_size(EVAL_SETS["最低件数を保証して還流(78)"]), 75)

p0 = zero_hit_rate()
rates = [min_detectable_rate(n, p0) for n in (20, 50, 100, 500, 1000)]
print("      窓ごとの最小検知幅: " + ", ".join(f"{r * 100:.1f}%" for r in rates))
check_true("窓が大きいほど小さな悪化を検知できる",
           all(a >= b for a, b in zip(rates, rates[1:])))
check_true("20件の窓では 10% 以上の悪化でないと有意にならない", rates[0] >= 0.10)
check_true("1000件の窓なら 6% 未満の悪化でも有意にできる", rates[-1] <= 0.06)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n横断復習04の検証はすべて成功しました。")
