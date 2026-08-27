#!/usr/bin/env python3
"""セッション5の自己検証：計画・分解・再計画が主張どおりに効いていること。

本文（body / practice / solutions）に載せた数値もここで検証している。
数値が変わる変更をしたときは、NG 行に出る実測値に合わせて本文の表を直すこと。
検証の前後で `tools/make_data.py` を走らせるので、データは初期状態に戻る。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from impact import REPORT_CHECKS, impact_facts, render_report, score_report  # noqa: E402
from measure import (BUDGET_CALLS, reset_data, run_all, run_newfact,  # noqa: E402
                     scored, trigger_cases, validation_cases)
from planner import PlanError, parse_plan, plan_cost, topo_layers  # noqa: E402
from plans import (PLAN_NOT_JSON, PLAN_OK, PLAN_OVERSPLIT, TURNS_FRAGMENTED,  # noqa: E402
                   TURNS_REPLAN, plan_from)
from runner import run_planned  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def ids(rows: list[dict]) -> list[str]:
    return [r["expense_id"] for r in rows]


# 方式ごとの期待値（台本で決まるので環境に依らず同じ値になる）
EXPECTED = {
    "noplan": {"plan_calls": 0, "exec_steps": 4, "llm_calls": 4, "tool_calls": 3,
               "score": 3, "stop_reason": "done"},
    "static_ok": {"plan_calls": 1, "exec_steps": 8, "llm_calls": 9, "tool_calls": 3,
                  "score": 5, "stop_reason": "done"},
    "static_broken": {"plan_calls": 1, "exec_steps": 8, "llm_calls": 9, "tool_calls": 3,
                      "score": 4, "stop_reason": "done"},
    "replan": {"plan_calls": 2, "exec_steps": 10, "llm_calls": 12, "tool_calls": 4,
               "score": 5, "stop_reason": "done"},
    "budget": {"plan_calls": 3, "exec_steps": 8, "llm_calls": 11, "tool_calls": 4,
               "score": 4, "stop_reason": "done"},
    "every": {"plan_calls": 6, "exec_steps": 10, "llm_calls": 16, "tool_calls": 4,
              "score": 5, "stop_reason": "done"},
    "fragmented": {"plan_calls": 1, "exec_steps": 8, "llm_calls": 9, "tool_calls": 3,
                   "score": 4, "stop_reason": "done"},
}

reset_data()

# --- 影響の計算：実データから決定的に出ていること -----------------------------
facts = impact_facts()
check("新たに事前承認が必要になる申請を特定できる",
      ids(facts["newly_approval"]) == ["EXP-0003"], str(ids(facts["newly_approval"])))
check("すでに事前承認の対象の申請は3件",
      ids(facts["already_approval"]) == ["EXP-0002", "EXP-0004", "EXP-0006"],
      str(ids(facts["already_approval"])))
check("新たに期限超過になる申請は4件",
      ids(facts["newly_late"]) == ["EXP-0002", "EXP-0003", "EXP-0005", "EXP-0006"],
      str(ids(facts["newly_late"])))
check("元から期限を超過していた申請は2件",
      ids(facts["already_late"]) == ["EXP-0001", "EXP-0004"],
      str(ids(facts["already_late"])))
full_score, full_missing = score_report(render_report(facts))
check("観点をすべて満たしたレポートは満点になる",
      full_score == len(REPORT_CHECKS) and not full_missing, f"{full_score} 点")

# --- 計画の構造：層に分けられること -------------------------------------------
plan_ok = plan_from(PLAN_OK)
layers = [[sg.id for sg in layer] for layer in topo_layers(plan_ok)]
check("計画が3つの層に分かれる（同じ層は同時に走らせられる）",
      layers == [["sg_policy", "sg_expenses"], ["sg_amount", "sg_deadline"],
                 ["sg_report"]], str(layers))
cost = plan_cost(plan_ok)
check("計画のコストを実行前に見積もれる",
      cost["subgoals"] == 5 and cost["min_llm_calls"] == 9, str(cost))

# --- 実行前の検証 -------------------------------------------------------------
cases = dict(validation_cases())
check("正しい計画には違反が無い", cases["正しい計画"] == [], str(cases["正しい計画"]))
over = cases["過分解（サブゴール10個）"]
check("過分解の計画から4件の違反を検出する", len(over) == 4, str(len(over)))
check("サブゴールの多すぎを検出する", any("多すぎます" in v for v in over))
check("未登録のツールを検出する", any("fetch_expenses" in v for v in over))
check("必要な情報を作る依存が無いことを検出する",
      sum(1 for v in over if "依存に入っていません" in v) == 2)
check("依存の循環を検出する",
      any("循環" in v for v in cases["依存が循環している計画"]),
      str(cases["依存が循環している計画"]))
try:
    parse_plan(PLAN_NOT_JSON)
    parse_msg = ""
except PlanError as exc:
    parse_msg = str(exc)
check("JSON でない計画はパースの段で止まる",
      "JSON として読めません" in parse_msg, parse_msg)
check("分解しすぎの計画は違反1件（文脈の分断）",
      len(cases["分解しすぎ（依存を書き忘れ）"]) == 1
      and "sg_amount_nocontext" in cases["分解しすぎ（依存を書き忘れ）"][0],
      str(cases["分解しすぎ（依存を書き忘れ）"]))

guarded = run_planned("検証あり", TURNS_FRAGMENTED, replan_policy="never")
check("違反のある計画は実行しない（1手も動かさない）",
      guarded.stop_reason == "invalid_plan" and guarded.exec_steps == 0
      and guarded.tool_calls == 0,
      f"stop_reason={guarded.stop_reason} / 手数={guarded.exec_steps}")

# --- 3方式の比較：数字が期待どおりであること ----------------------------------
runs = run_all()
for key, want in EXPECTED.items():
    res = runs[key]
    score, _ = scored(res)
    got = {"plan_calls": res.plan_calls, "exec_steps": res.exec_steps,
           "llm_calls": res.llm_calls, "tool_calls": res.tool_calls,
           "score": score, "stop_reason": res.stop_reason}
    check(f"{res.label}の数字が本文の表と一致する", got == want, str(got))

check("計画なしが最も安く、最も抜けが多い",
      runs["noplan"].llm_calls == min(r.llm_calls for r in runs.values())
      and scored(runs["noplan"])[0] == min(scored(r)[0] for r in runs.values()),
      f"LLM {runs['noplan'].llm_calls} 回 / {scored(runs['noplan'])[0]} 点")

# --- 静的計画の脆さ：done なのに成果物が不完全 --------------------------------
broken = runs["static_broken"]
score_b, missing_b = scored(broken)
check("静的計画は失敗しても done で終わる（黙って壊れる）",
      broken.stop_reason == "done" and broken.failed_tool_calls == 1,
      f"stop_reason={broken.stop_reason} / 失敗した呼び出し {broken.failed_tool_calls}")
check("その成果物からは現行規程の出典が落ちている",
      missing_b == ["現行規程の出典を示している"], str(missing_b))
check("静的計画では再計画が起きない", broken.replans == [], str(broken.replans))

# --- 逐次再計画：失敗をきっかけに1回だけ作り直す ------------------------------
replan = runs["replan"]
check("再計画は失敗をきっかけに1回だけ起きる",
      len(replan.replans) == 1 and replan.replans[0].startswith("tool_failure"),
      str(replan.replans))
check("再計画のきっかけになったエラーが次の行動を示している",
      "指定できる項目" in replan.replans[0], replan.replans[0][:60] + "…")
check("完了したサブゴールを二度実行しない",
      replan.tool_names == ["get_policy", "get_policy", "list_expenses", "write_file"],
      str(replan.tool_names))
check("再計画した結果、成果物が満点になる", scored(replan)[0] == len(REPORT_CHECKS))
check("正しさのために入力トークンを追加で払っている",
      replan.total_tokens["input"] > broken.total_tokens["input"],
      f"再計画 {replan.total_tokens['input']} > 静的 {broken.total_tokens['input']}")

# --- 予算トリガ：縮小した計画で成果物を残す ------------------------------------
budget = runs["budget"]
check("予算の上限を超えずに終わる",
      budget.llm_calls <= BUDGET_CALLS, f"{budget.llm_calls} 回 / 上限 {BUDGET_CALLS} 回")
check("失敗と予算の2つのトリガが順に立つ",
      len(budget.replans) == 2 and budget.replans[0].startswith("tool_failure")
      and budget.replans[1].startswith("budget"), str(budget.replans))
check("縮小した計画でも成果物を残し、未調査を明記する",
      "未調査" in budget.report and budget.report_path == "impact_budget.md",
      budget.report_path)

# --- 毎サブゴール再計画：同じ成果に3倍の計画コスト ----------------------------
every = runs["every"]
check("毎サブゴール再計画は計画呼び出しが3倍になる",
      every.plan_calls == 3 * replan.plan_calls,
      f"{every.plan_calls} 回 vs {replan.plan_calls} 回")
check("それでも成果物は1文字も変わらない",
      every.report == replan.report and every.exec_steps == replan.exec_steps,
      f"手数 {every.exec_steps} / {replan.exec_steps}")

# --- 分解しすぎ：文脈が分断されて観点が落ちる ---------------------------------
frag = runs["fragmented"]
score_f, missing_f = scored(frag)
check("分解しすぎると観点が落ちたまま done で終わる",
      frag.stop_reason == "done" and missing_f == ["金額基準の影響を特定している"],
      str(missing_f))
check("落ちた観点は成果物に「特定できませんでした」として現れる",
      "特定できませんでした" in frag.report)

# --- 新情報トリガ：サブゴールを1つ足して通す ----------------------------------
nf = run_newfact()
check("新情報をきっかけに1回だけ作り直す",
      len(nf.replans) == 1 and nf.replans[0].startswith("new_fact"), str(nf.replans))
check("サブゴールを1つ足したぶんだけコストが増える",
      (nf.plan_calls, nf.exec_steps, nf.llm_calls, nf.tool_calls) == (2, 9, 11, 3),
      f"計画 {nf.plan_calls} / 手数 {nf.exec_steps} / LLM {nf.llm_calls} / "
      f"ツール {nf.tool_calls}")
check("追加したサブゴールでもツールは増えない（集計のみ）",
      nf.tool_names == ["get_policy", "list_expenses", "write_file"], str(nf.tool_names))
check("新情報を織り込んだ成果物が満点になる",
      scored(nf)[0] == len(REPORT_CHECKS), f"{scored(nf)[0]} 点")

# --- トリガの単体判定 ---------------------------------------------------------
triggers = dict(trigger_cases())
check("失敗トリガが立つ",
      (triggers["失敗（ツール結果が失敗）"] or "").startswith("tool_failure"),
      str(triggers["失敗（ツール結果が失敗）"]))
check("新情報トリガが立つ",
      (triggers["新情報（計画が触れていない語が結果に出た）"] or "").startswith("new_fact"),
      str(triggers["新情報（計画が触れていない語が結果に出た）"]))
check("予算トリガが立つ",
      (triggers["予算（残りで計画を実行しきれない）"] or "").startswith("budget"),
      str(triggers["予算（残りで計画を実行しきれない）"]))
check("何も起きていなければ作り直さない",
      triggers["どれも立たない（作り直さない）"] is None,
      str(triggers["どれも立たない（作り直さない）"]))

# --- 決定性：2回走らせて同じ結果になる ----------------------------------------
a = run_planned("逐次再計画", TURNS_REPLAN, replan_policy="on_trigger")
b = run_planned("逐次再計画", TURNS_REPLAN, replan_policy="on_trigger")
check("同じ入力で2回走らせて軌跡と成果物が一致する",
      a.tool_names == b.tool_names and a.report == b.report
      and a.total_tokens == b.total_tokens and a.replans == b.replans,
      f"{a.tool_names} / {a.total_tokens}")

# --- 成果物が実際に作業領域へ書かれている ------------------------------------
saved = ROOT / "workspace" / "impact.md"
check("満点のレポートが作業領域に保存されている",
      saved.exists() and saved.read_text(encoding="utf-8") == a.report,
      str(saved.relative_to(ROOT)))
check("方式ごとに別の成果物が残る",
      all((ROOT / "workspace" / name).exists() for name in
          ("impact_noplan.md", "impact_static_broken.md", "impact_budget.md",
           "impact_fragmented.md")))

# --- 計画のコスト：分解を増やすと計画そのものが重くなる -----------------------
c_small = plan_cost(plan_from(PLAN_OK))
c_large = plan_cost(plan_from(PLAN_OVERSPLIT))
check("分解を増やすと計画の近似トークンも最低呼び出し回数も増える",
      c_large["approx_plan_tokens"] > c_small["approx_plan_tokens"]
      and c_large["min_llm_calls"] > c_small["min_llm_calls"],
      f"{c_small} → {c_large}")

# --- 引き継げる成果物：runbook が決定的に生成される ---------------------------
from runbook import SECTIONS, build_runbook  # noqa: E402

rb1 = build_runbook(runs)
rb2 = build_runbook(run_all())
check("runbook に5つの節がすべてある",
      all(s in rb1 for s in SECTIONS), f"{len(rb1)} 文字")
check("runbook を2回生成して1文字も変わらない", rb1 == rb2)
check("runbook の比較表に全方式が載る",
      all(r.label in rb1 for r in runs.values()))

reset_data()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション5の検証はすべて成功しました。")
