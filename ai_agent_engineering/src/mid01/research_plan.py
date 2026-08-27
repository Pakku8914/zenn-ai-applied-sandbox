#!/usr/bin/env python3
"""調査の計画（S05）と、計画を状態機械（S06）と突き合わせる検査。

    python src/mid01/research_plan.py

この章では計画を**モデルに立てさせない**。理由は3つある。
  1. 調査の手順は事前に決まる（毎回同じ4段である）
  2. 立てさせると計画のために1手ぶん余分にモデルを呼ぶ
  3. 計画が壊れているときの分岐（`invalid_plan`）を、毎回通す必要がない

そのぶん、計画は**実行前に検査する**。S05 の `validate_plan()` に加えて、
「そのサブゴールを実行する状態が決まっているか」「その状態でその道具が使えるか」を
見る。ここで落ちたら1手もモデルを呼ばずに人へ渡す。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from planner import (Plan, SubGoal, mermaid_dag, plan_cost,  # noqa: E402
                     render_plan_md, topo_layers, validate_plan)

from machine import STATE_TOOLS  # noqa: E402

RESEARCH_PLAN = Plan(
    goal="経費規程に照らして事前承認の記録がない申請を洗い出し、根拠付きで報告する",
    subgoals=(
        SubGoal(id="sg_policy", goal="判定基準となる規程を特定する",
                tools=("get_policy",), produces=("threshold",), max_steps=2),
        SubGoal(id="sg_expenses", goal="基準額以上で未承認の申請を集める",
                tools=("find_expenses",), needs=("sg_policy",), consumes=("threshold",),
                produces=("candidates",), max_steps=2),
        SubGoal(id="sg_context", goal="判断の背景になる手順書を確認する",
                tools=("search_docs",), needs=("sg_policy",), consumes=("threshold",),
                produces=("context",), max_steps=1),
        SubGoal(id="sg_report", goal="根拠付きのレポートを作る",
                tools=("write_file",), needs=("sg_expenses", "sg_context"),
                consumes=("candidates", "context"), produces=("report",), max_steps=2),
    ),
)

# サブゴールを、どの状態で実行するか。計画と状態機械はここで1対1につながる
SUBGOAL_STATES = {
    "sg_policy": "collecting",
    "sg_expenses": "collecting",
    "sg_context": "collecting",
    "sg_report": "drafting",
}


def _rename_last(plan: Plan, new_id: str) -> Plan:
    """最後のサブゴールの id だけを差し替えた計画（検査を試すための壊れた計画）。"""
    last = plan.subgoals[-1]
    return Plan(goal=plan.goal, subgoals=(
        *plan.subgoals[:-1],
        SubGoal(new_id, last.goal, last.tools, last.needs, last.consumes,
                last.produces, last.max_steps),
    ))


def _replace_last_tools(plan: Plan, tools: tuple[str, ...]) -> Plan:
    """最後のサブゴールの道具だけを差し替えた計画。"""
    last = plan.subgoals[-1]
    return Plan(goal=plan.goal, subgoals=(
        *plan.subgoals[:-1],
        SubGoal(last.id, last.goal, tools, last.needs, last.consumes,
                last.produces, last.max_steps),
    ))


# 状態が割り当てられていないサブゴールを持つ計画（S05 の検査だけでは通ってしまう）
PLAN_UNMAPPED = _rename_last(RESEARCH_PLAN, "sg_wrapup")

# 持っていない道具を指定した計画（S05 の検査で落ちる ＋ 状態の検査でも落ちる）
PLAN_FORBIDDEN = _replace_last_tools(RESEARCH_PLAN, ("send_message",))


def check_plan(plan: Plan, tool_names, *, mapping=None, state_tools=None) -> list[str]:
    """計画を実行前に検査する。違反の一覧を返す（空なら合格）。

    S05 の8点検査（未登録ツール・依存の欠け・循環・成果キー・分解しすぎ など）に、
    S06 の状態との整合を足している。
    """
    mapping = SUBGOAL_STATES if mapping is None else mapping
    state_tools = STATE_TOOLS if state_tools is None else state_tools

    violations = list(validate_plan(plan, list(tool_names), requires=("report",)))
    for sg in plan.subgoals:
        state = mapping.get(sg.id)
        if state is None:
            violations.append(
                f"{sg.id}: 実行する状態が割り当てられていません"
                f"（割り当て済み: {', '.join(sorted(mapping)) or 'なし'}）")
            continue
        allowed = state_tools.get(state, ())
        for tool in sg.tools:
            if tool not in allowed:
                violations.append(
                    f"{sg.id}: ツール '{tool}' は状態 '{state}' では使えません"
                    f"（この状態で使えるツール: {', '.join(allowed) or 'なし'}）")
    return violations


def render_state_map() -> str:
    """サブゴールと状態の対応表（設計レビューに回す成果物）。"""
    lines = ["| サブゴール | 実行する状態 | 使う道具 | 作る情報 |",
             "| :--- | :--- | :--- | :--- |"]
    for sg in RESEARCH_PLAN.subgoals:
        lines.append(f"| {sg.id} | {SUBGOAL_STATES.get(sg.id, '（未割り当て）')} | "
                     f"{', '.join(sg.tools) or '-'} | {', '.join(sg.produces) or '-'} |")
    return "\n".join(lines)


def main() -> None:
    from spec import build_registry  # noqa: PLC0415

    tool_names = build_registry().names()
    print("=== 計画（成果物②の前半） ===")
    print(render_plan_md(RESEARCH_PLAN))
    print(render_state_map())
    print()
    print(f"計画そのもののコスト: {plan_cost(RESEARCH_PLAN)}")
    print()
    for label, plan in (("正しい計画", RESEARCH_PLAN),
                        ("状態が割り当てられていない計画", PLAN_UNMAPPED),
                        ("持っていない道具を指定した計画", PLAN_FORBIDDEN)):
        violations = check_plan(plan, tool_names)
        print(f"--- {label}: 違反 {len(violations)} 件")
        for v in violations:
            print(f"  - {v}")
    print()
    print("=== 依存の層（同じ層は互いに依存していない） ===")
    for i, layer in enumerate(topo_layers(RESEARCH_PLAN)):
        print(f"層{i}: {', '.join(sg.id for sg in layer)}")
    print()
    print("=== 計画の DAG（Mermaid） ===")
    print(mermaid_dag(RESEARCH_PLAN))


if __name__ == "__main__":
    main()
