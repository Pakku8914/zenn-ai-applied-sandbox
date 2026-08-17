#!/usr/bin/env python3
"""セッション14の自己検証：参照グラフとマルチホップ探索が決定的に回ること。

  1. 参照名の辞書・言及・エッジの数が固定シードのコーパスから決まる値になること
  2. テーマをまたぐエッジが3本しかないこと（グラフの正味の価値）
  3. 曖昧な参照の解決方針（all / newest）で結果が変わること
  4. マルチホップ質問が上位10件では解けず、delegates_to の1ホップで解けること
  5. 親子チャンクでは解けないこと／参照追跡（多段検索）では解けること
  6. 集約質問がメタデータ集計で正確に解けること
  7. LLM 抽出（StubClient）がルールベースと同じ答えを出すこと
  8. タイトルを1つ変えるとエッジが静かに壊れ、リンク切れ検査で検出できること

埋め込みモデルもリランカも使わない。APIキーも不要（StubClient のみ）。
期待値と一致しなければ非0で終了する。
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aggregate import category_counts, cross_tab, dept_counts, source_type_counts  # noqa: E402
from alternatives import follow_references, parent_child_hits  # noqa: E402
from cost_model import calls, llm_extract, make_stub  # noqa: E402
from graph_lab import (  # noqa: E402
    CANDIDATE_K,
    CONTEXT_K,
    MULTIHOP_QUESTIONS,
    Bench,
    DocGraph,
    build_name_index,
    candidate_expressions,
    dangling_references,
    hop_report,
)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


EXPECTED_IDS = {
    "情報の持ち出しに関する補則": "DOC-0299",
    "外部サービスの利用申請に関する補則": "DOC-0300",
    "PCの返却に関する補則": "DOC-0301",
    "USBメモリの利用規程": "DOC-0271",
    "セキュリティ事故の報告規程": "DOC-0288",
    "退職時のアカウント停止規程": "DOC-0190",
    "有給休暇の申請に関するよくある質問（1）": "DOC-0004",
    "有給休暇の申請規程（2026年度版）": "DOC-0007",
    "有給休暇の申請規程（2023年度版・旧規程）": "DOC-0008",
}

bench = Bench()
docs = bench.docs
g = bench.graph
index = build_name_index(docs)

# --- 前提（コーパスと文書の対応）-------------------------------------------
check("コーパスが 301 文書・6 部署", len(docs) == 301 and len(g.depts) == 6,
      f"{len(docs)} 文書 / {len(g.depts)} 部署")
check("ノード数が 307（文書301 + 部署6）", g.n_nodes == 307, f"{g.n_nodes}")
mismatched = {t: bench.by_title.get(t, "（そのタイトルの文書が無い）")
              for t, i in EXPECTED_IDS.items() if bench.by_title.get(t) != i}
check("章で名指しする文書の doc_id が期待どおり", not mismatched, f"ずれ {mismatched}")

# --- 1. 辞書と言及 -----------------------------------------------------------
covered = sum(len(v) for v in index.values())
ambiguous_names = [n for n, ids in index.items() if len(ids) > 1]
check("参照名の辞書が 115 項目・157 文書をカバー",
      len(index) == 115 and covered == 157, f"{len(index)} 項目 / {covered} 文書")
check("複数文書を指す参照名が 42 項目", len(ambiguous_names) == 42, f"{len(ambiguous_names)}")

ambiguous = [m for m in g.mentions if m.ambiguous]
check("本文から拾った言及が 255 件", len(g.mentions) == 255, f"{len(g.mentions)}")
check("うち参照先が絞れない言及が 120 件", len(ambiguous) == 120, f"{len(ambiguous)}")
check("自己参照は 0 件", all(m.src not in m.candidates for m in g.mentions))

kinds = Counter(m.kind for m in g.mentions)
check("言及の型が related 144 / mentions 108 / delegates_to 3",
      kinds["related"] == 144 and kinds["mentions"] == 108 and kinds["delegates_to"] == 3,
      f"{dict(kinds)}")

# --- 2. エッジ ---------------------------------------------------------------
check("エッジ（link=all）が 375 本", len(g.edges) == 375, f"{len(g.edges)}")
check("エッジの型が related 156 / mentions 216 / delegates_to 3",
      len(g.edges_of("related")) == 156 and len(g.edges_of("mentions")) == 216
      and len(g.edges_of("delegates_to")) == 3,
      f"{[len(g.edges_of(k)) for k in ('related', 'mentions', 'delegates_to')]}")
check("参照を持つ文書 183 / 参照される文書 150",
      len(g.adj_out) == 183 and len(g.adj_in) == 150,
      f"{len(g.adj_out)} / {len(g.adj_in)}")

cross = g.cross_theme_edges()
expected_cross = {("DOC-0299", "DOC-0271"), ("DOC-0300", "DOC-0288"), ("DOC-0301", "DOC-0190")}
check("テーマをまたぐエッジは 3 本だけ", len(cross) == 3, f"{len(cross)} / {len(g.edges)}")
check("そのすべてが delegates_to で、期待どおりの組",
      {(e.src, e.dst) for e in cross} == expected_cross
      and all(e.kind == "delegates_to" for e in cross))

usb = bench.doc_id("USBメモリの利用規程")
old_policy = bench.doc_id("有給休暇の申請規程（2023年度版・旧規程）")
check("USBメモリの利用規程は 3 本から参照される（手順書2 + 補則1）",
      g.in_degree(usb) == 3, f"{g.in_degree(usb)}")
check("旧規程も 2 本の参照を集めてしまう（link=all の代償）",
      g.in_degree(old_policy) == 2, f"{g.in_degree(old_policy)}")
detail_docs = [d.doc_id for d in docs if d.title.endswith("（管理職限定）")]
check("管理職限定の運用細則は誰からも参照されない",
      len(detail_docs) == 4 and all(g.in_degree(i) == 0 for i in detail_docs),
      f"{len(detail_docs)} 件")

# --- 3. 曖昧な参照の解決方針 -------------------------------------------------
newest = DocGraph(docs, link="newest")
check("link=newest ならエッジは言及と同数の 255 本", len(newest.edges) == 255,
      f"{len(newest.edges)}")
sample = next(m for m in g.mentions if m.ambiguous and m.name.endswith("規程"))
check("link=newest は旧規程を選ばない",
      newest.resolve(sample) == (bench.doc_id("有給休暇の申請規程（2026年度版）"),),
      f"{newest.resolve(sample)}")
check("link=newest だと旧規程への参照が 0 になる",
      newest.in_degree(old_policy) == 0, f"{newest.in_degree(old_policy)}")

# --- 4. 探索 -----------------------------------------------------------------
bridges = {bench.doc_id(q.bridge_title) for q in MULTIHOP_QUESTIONS}
check("補則3件から1ホップで6文書に広がる", len(g.expand(bridges, hops=1)) == 6,
      f"{len(g.expand(bridges, hops=1))}")
check("2ホップに増やしても6文書のまま（規程は参照を持たない）",
      len(g.expand(bridges, hops=2)) == 6, f"{len(g.expand(bridges, hops=2))}")
faq = bench.doc_id("有給休暇の申請に関するよくある質問（1）")
sizes = [len(g.expand({faq}, hops=h)) for h in (1, 2, 3)]
check("FAQ から 1→2→3 ホップで 3 / 6 / 6 文書", sizes == [3, 6, 6], f"{sizes}")
check("2ホップ先には旧規程が混ざる", old_policy in g.expand({faq}, hops=2))

# --- 5. マルチホップ質問 ------------------------------------------------------
reports = [hop_report(bench, q) for q in MULTIHOP_QUESTIONS]
check(f"上位{CONTEXT_K}件に答えが載った質問は 0 件",
      sum(r["answer_in_top"] for r in reports) == 0,
      f"{[r['qid'] for r in reports if r['answer_in_top']]}")
check(f"候補{CANDIDATE_K}件には起点の文書が入る",
      all(r["bridge_in_cand"] for r in reports),
      f"{[r['qid'] for r in reports if not r['bridge_in_cand']]}")
check("delegates_to の1ホップで3問とも答えの文書に到達する",
      all(r["answer_reached"] for r in reports),
      f"{sum(r['answer_reached'] for r in reports)}/3")
check("型を絞った拡張で増える文書は3件以内",
      all(r["added_typed"] <= 3 for r in reports),
      f"{[r['added_typed'] for r in reports]}")
check("型を絞らない拡張のほうが多くの文書を足す",
      all(r["added_untyped"] >= r["added_typed"] for r in reports),
      f"{[(r['added_untyped'], r['added_typed']) for r in reports]}")
check("経路はすべて1ホップ", all(len(r["path"]) == 2 for r in reports),
      f"{[len(r['path']) - 1 for r in reports]}")

# --- 6. 代替策 ---------------------------------------------------------------
parent_ok = [q.qid for q in MULTIHOP_QUESTIONS if parent_child_hits(bench, q)]
check("親子チャンクでは1問も解けない（文書をまたげない）", not parent_ok, f"{parent_ok}")
follow_ok = 0
follow_calls = []
for q in MULTIHOP_QUESTIONS:
    _, names, reached = follow_references(bench, q)
    follow_calls.append(len(names))
    follow_ok += int(bench.has_answer(reached, q.fact))
check("参照追跡（多段検索）は3問とも解ける", follow_ok == 3, f"{follow_ok}/3")
check("参照追跡は質問のたびに追加の検索が要る", all(n >= 1 for n in follow_calls),
      f"追加検索 {follow_calls} 回")

# --- 7. 集約質問 -------------------------------------------------------------
expected_category = {"PC・端末": 49, "アカウント": 50, "オフィス": 49,
                     "セキュリティ": 52, "勤怠": 51, "経費": 50}
expected_dept = {"人事部": 16, "情報システム部": 99, "情報セキュリティ室": 52,
                 "所属長": 26, "経理部": 34, "総務部": 74}
expected_cross_tab = {
    "PC・端末": {"faq": 18, "notice": 6, "policy": 7, "procedure": 18},
    "アカウント": {"faq": 18, "notice": 6, "policy": 8, "procedure": 18},
    "オフィス": {"faq": 18, "notice": 6, "policy": 7, "procedure": 18},
    "セキュリティ": {"faq": 18, "notice": 6, "policy": 10, "procedure": 18},
    "勤怠": {"faq": 18, "notice": 6, "policy": 9, "procedure": 18},
    "経費": {"faq": 18, "notice": 6, "policy": 8, "procedure": 18},
}
check("カテゴリ別の件数が集計で正確に出る", category_counts(docs) == expected_category,
      f"{category_counts(docs)}")
check("所管部署別の件数が集計で正確に出る", dept_counts(docs) == expected_dept,
      f"{dept_counts(docs)}")
check("種別別の件数が faq108 / notice36 / policy49 / procedure108",
      source_type_counts(docs) == {"faq": 108, "notice": 36, "policy": 49, "procedure": 108},
      f"{source_type_counts(docs)}")
check("カテゴリ×種別のクロス集計が一致", cross_tab(docs) == expected_cross_tab)
counted = len(bench.search_docs("セキュリティに関する文書は全部で何件ありますか", k=CONTEXT_K))
check("上位k件からは件数を数えられない（52 件に届かない）",
      counted <= CONTEXT_K < expected_category["セキュリティ"], f"検索で得た文書 {counted} 件")

# --- 8. LLM 抽出（StubClient）------------------------------------------------
stub = make_stub()
same = 0
for e in cross:
    got = llm_extract(stub, bench.by_id[e.src], index)
    rule = tuple(sorted(g.neighbors(e.src, kinds=("delegates_to",))))
    same += int(got == rule)
check("StubClient の抽出結果がルールベースと一致する（3件）", same == 3, f"{same}/3")
check("LLM 抽出の呼び出し回数の見積もりが 301 / 1204",
      calls(len(docs)) == 301 and calls(len(docs), 2, 2) == 1204)
check("テーマをまたぐエッジ1本あたり 100.3 回の呼び出し",
      abs(calls(len(docs)) / len(cross) - 100.333) < 0.01,
      f"{calls(len(docs)) / len(cross):.1f}")

# --- 9. リンク切れ検査と維持コスト -------------------------------------------
structural = sum(len(candidate_expressions(d)) for d in docs)
check("書式から拾える参照表現が 147 件・リンク切れ 0 件",
      structural == 147 and not dangling_references(docs, index),
      f"{structural} 件 / リンク切れ {len(dangling_references(docs, index))} 件")

renamed = [replace(d, title="USBメモリ等の外部記録媒体の利用規程") if d.doc_id == usb else d
           for d in docs]
g2 = DocGraph(renamed)
dangling2 = dangling_references(renamed, build_name_index(renamed))
check("タイトルを1つ変えるとエッジが 375 -> 372 に減る", len(g2.edges) == 372,
      f"{len(g2.edges)}")
check("その文書への参照が 3 -> 0 になる", g2.in_degree(usb) == 0, f"{g2.in_degree(usb)}")
check("リンク切れ検査なら 3 件として検出できる", len(dangling2) == 3, f"{len(dangling2)}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション14の検証はすべて成功しました。")
