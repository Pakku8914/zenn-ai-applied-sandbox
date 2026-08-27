#!/usr/bin/env python3
"""計画を「引き継げる成果物」にする（問題10の参照実装）。

    python src/session05/runbook.py

出力は workspace/plan_runbook.md。時刻も乱数も使わないので、
何度実行しても1文字も変わらない（差分レビューに載せられる）。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from impact import REPORT_CHECKS, TASK  # noqa: E402
from measure import BUDGET_CALLS, run_all, scored  # noqa: E402
from planner import mermaid_dag, plan_cost, render_plan_md, topo_layers  # noqa: E402
from plans import PLAN_OK, plan_from  # noqa: E402
from runner import RunResult  # noqa: E402

OUT = ROOT / "workspace" / "plan_runbook.md"
SECTIONS = ("## 1. 対象タスクと採点基準", "## 2. 計画と依存グラフ", "## 3. 方式の比較",
            "## 4. 再計画のログ", "## 5. 運用の判断メモ")


def build_runbook(runs: dict[str, RunResult]) -> str:
    plan = plan_from(PLAN_OK)
    cost = plan_cost(plan)
    out: list[str] = ["# 規程改定の影響調査エージェント runbook", "",
                      SECTIONS[0], "", "対象タスク:", "", f"> {TASK}", "",
                      "成果物の採点基準（すべて満たして満点）:", ""]
    out += [f"{i}. {label}" for i, (label, _) in enumerate(REPORT_CHECKS, start=1)]

    out += ["", SECTIONS[1], "", render_plan_md(plan).rstrip(), ""]
    out.append("実行順（同じ層は互いに依存していない）:")
    out += [f"- 層{i}: {', '.join(sg.id for sg in layer)}"
            for i, layer in enumerate(topo_layers(plan))]
    out += ["", "```mermaid", mermaid_dag(plan), "```", ""]

    out += [SECTIONS[2], "",
            "| 方式 | 計画 | 手数 | LLM 合計 | ツール | 成果物 | 停止理由 | 欠けた観点 |",
            "| :--- | --: | --: | --: | --: | :--- | :--- | :--- |"]
    for res in runs.values():
        score, missing = scored(res)
        out.append(f"| {res.label} | {res.plan_calls} | {res.exec_steps} | {res.llm_calls} "
                   f"| {res.tool_calls} | {score}/{len(REPORT_CHECKS)} | {res.stop_reason} "
                   f"| {', '.join(missing) or 'なし'} |")

    out += ["", SECTIONS[3], ""]
    for key in ("replan", "budget", "every"):
        res = runs[key]
        out.append(f"- {res.label}（計画の呼び出し {res.plan_calls} 回）")
        out += [f"    {i}. {reason}" for i, reason in enumerate(res.replans, start=1)] \
            or ["    （再計画なし）"]

    replan, static_ok, noplan = runs["replan"], runs["static_ok"], runs["noplan"]
    out += [
        "", SECTIONS[4], "",
        f"- 採用する方式: 逐次再計画（LLM {replan.llm_calls} 回 / 成果物 "
        f"{scored(replan)[0]}/{len(REPORT_CHECKS)} 点）",
        f"- 理由: 静的計画は前提が外れると停止理由 done のまま "
        f"{scored(runs['static_broken'])[0]}/{len(REPORT_CHECKS)} 点で終わる。"
        f"計画なしは LLM {noplan.llm_calls} 回で最も安いが "
        f"{scored(noplan)[0]}/{len(REPORT_CHECKS)} 点しか出ない",
        f"- サブゴールの max_steps 合計: {cost['min_llm_calls'] - 1} 回"
        f"（計画の呼び出し1回を足した下限が {cost['min_llm_calls']} 回）",
        f"- budget_calls の設定値: {BUDGET_CALLS} 回（下限 {cost['min_llm_calls']} 回に、"
        "失敗1回ぶんの作り直し（サブゴール2手＋計画1回）を足した値）",
        f"- max_replans の設定値: 3 回（実測での再計画は最大 "
        f"{max(len(r.replans) for r in runs.values())} 回。"
        "毎サブゴール再計画では計画の呼び出しが "
        f"{runs['every'].plan_calls} 回に増えるだけで成果物は変わらない）",
        f"- 静的計画に切り替える条件: 同じ計画で失敗トリガが30日間立たなくなったら、"
        f"計画の呼び出しを1回に減らせる（LLM {static_ok.llm_calls} 回）",
    ]
    return "\n".join(out) + "\n"


def main() -> None:
    text = build_runbook(run_all())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} を書き出しました（{len(text)} 文字）。")
    print(text)


if __name__ == "__main__":
    main()
