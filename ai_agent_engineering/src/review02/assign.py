#!/usr/bin/env python3
"""復習02：分割を「計画」として書き、配る前に検査する（S05 × S08）。

    docker compose exec app python src/review02/assign.py

S05 では計画を構造として持ち、実行の前に `validate_plan()` で検査した。
分割（誰にどのサブゴールを任せるか）も同じ性質の設計物である。配ってから
「権限が広すぎた」「引き継ぎが多すぎた」と気づくのでは遅い。

`agentkit` と S05 の `planner.py` は1行も変更しない。足すのは
**担当への割り当てを検査する層**（`check_assignment`）だけである。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from agentkit.biztools import build_registry  # noqa: E402
from planner import (Plan, SubGoal, mermaid_dag, plan_cost,  # noqa: E402 (S05)
                     topo_layers, validate_plan)

# 引き継ぎの上限。渡すたびに文脈が落ちるので、回数そのものを設計値にする
MAX_HANDOFFS = 1

TEAM_PLAN = Plan(
    goal="四半期の棚卸しをレポートにして報告会の部屋を押さえる",
    subgoals=(
        SubGoal("sg_collect", "規程と申請一覧を集める",
                tools=("get_policy", "list_expenses", "search_docs"),
                produces=("policy", "expenses"), max_steps=3),
        SubGoal("sg_check", "規程違反の疑いを洗い出す",
                needs=("sg_collect",), consumes=("policy", "expenses"),
                produces=("violations",), max_steps=1),
        SubGoal("sg_report", "レポートに保存する", tools=("write_file",),
                needs=("sg_check",), consumes=("violations",),
                produces=("report",), max_steps=1),
        SubGoal("sg_book", "報告会の会議室を予約する", tools=("book_room",),
                needs=("sg_report",), consumes=("report",),
                produces=("booking",), max_steps=2),
    ),
)

# 依存が担当をまたぐのを1回に抑えた割り当て
GOOD_ASSIGNMENT = {
    "researcher": ("sg_collect", "sg_check"),
    "arranger": ("sg_report", "sg_book"),
}

# 予約だけ調査担当に戻してしまった割り当て（現場で本当に起きる形）
BAD_ASSIGNMENT = {
    "researcher": ("sg_collect", "sg_check", "sg_book"),
    "arranger": ("sg_report",),
}

# 予約の担当が決まっていない割り当て
MISSING_ASSIGNMENT = {
    "researcher": ("sg_collect", "sg_check"),
    "arranger": ("sg_report",),
}

# 実行前に止まる計画（report を作る人がいないのに report を要求している）
BROKEN_PLAN = Plan(
    goal="集めて予約する",
    subgoals=(
        SubGoal("sg_collect", "規程を集める", tools=("get_policy",),
                produces=("policy",), max_steps=2),
        SubGoal("sg_book", "会議室を予約する", tools=("book_room",),
                needs=("sg_collect",), consumes=("report",), max_steps=2),
    ),
)


def owner_of(assignment: dict) -> dict:
    """サブゴール id → 担当。重複しているときは先に書かれた担当を採る。"""
    owners: dict[str, str] = {}
    for owner, ids in assignment.items():
        for sg_id in ids:
            owners.setdefault(sg_id, owner)
    return owners


def tools_of(plan: Plan, assignment: dict, owner: str) -> list[str]:
    """その担当に渡すことになるツール名（＝許可リスト）。"""
    names: set[str] = set()
    for sg_id in assignment.get(owner, ()):
        subgoal = plan.get(sg_id)
        if subgoal is not None:
            names |= set(subgoal.tools)
    return sorted(names)


def handoff_count(plan: Plan, assignment: dict) -> int:
    """依存が担当をまたぐ回数。またぐたびに文脈が落ちる。"""
    owners = owner_of(assignment)
    crossings = 0
    for subgoal in plan.subgoals:
        for need in subgoal.needs:
            src, dst = owners.get(need), owners.get(subgoal.id)
            if src is None or dst is None:
                continue  # 割り当てられていない側は別の違反として報告する
            if src != dst:
                crossings += 1
    return crossings


def check_assignment(plan: Plan, assignment: dict, registry, *,
                     max_handoffs: int = MAX_HANDOFFS) -> list[str]:
    """割り当ての違反を並べる（空なら配ってよい）。判定の順序を固定する。"""
    violations: list[str] = []
    owners = owner_of(assignment)

    unassigned = [sg.id for sg in plan.subgoals if sg.id not in owners]
    if unassigned:
        violations.append(
            f"割り当てられていないサブゴール: {', '.join(unassigned)}")

    assigned = [sg_id for ids in assignment.values() for sg_id in ids]
    duplicated = sorted({i for i in assigned if assigned.count(i) > 1})
    if duplicated:
        violations.append(
            f"2人以上に割り当てられているサブゴール: {', '.join(duplicated)}")

    for owner in assignment:
        read, write = [], []
        for name in tools_of(plan, assignment, owner):
            tool = registry.get(name)
            if tool is None:
                continue
            if "write" in tool.tags:
                write.append(name)
            elif "read" in tool.tags:
                read.append(name)
        if read and write:
            violations.append(
                f"{owner}: 読み取り専用と副作用のあるツールが混ざっています"
                f"（read: {', '.join(read)} / write: {', '.join(write)}）")

    crossings = handoff_count(plan, assignment)
    if crossings > max_handoffs:
        violations.append(
            f"引き継ぎが {crossings} 回あります（上限 {max_handoffs} 回）。"
            "渡すたびに文脈が落ちます")
    return violations


def render_team_mermaid(plan: Plan, assignment: dict) -> str:
    """担当ごとに囲んだ DAG。引き継ぎの矢印に印を付ける（引き継げる成果物）。"""
    owners = owner_of(assignment)
    lines = ["flowchart LR"]
    for owner, ids in assignment.items():
        lines.append(f"  subgraph {owner}")
        for sg_id in ids:
            lines.append(f"    {sg_id}[\"{sg_id}\"]")
        lines.append("  end")
    for subgoal in plan.subgoals:
        for need in subgoal.needs:
            crossed = owners.get(need) != owners.get(subgoal.id)
            label = "|引き継ぎ|" if crossed else ""
            lines.append(f"  {need} -->{label} {subgoal.id}")
    return "\n".join(lines)


def main() -> None:
    registry = build_registry()
    names = registry.names()

    print("=== 計画そのものの検査（S05 の validate_plan）===")
    print(f"違反: {validate_plan(TEAM_PLAN, names)}")
    cost = plan_cost(TEAM_PLAN)
    print(f"サブゴール: {cost['subgoals']} / 最低の LLM 呼び出し回数: "
          f"{cost['min_llm_calls']}")
    print(f"層: {[[sg.id for sg in layer] for layer in topo_layers(TEAM_PLAN)]}")
    print(f"止まる計画の違反: {len(validate_plan(BROKEN_PLAN, names))} 件")
    for violation in validate_plan(BROKEN_PLAN, names):
        print(f"  - {violation}")

    print()
    print("=== 割り当ての検査（復習02 で足す層）===")
    for label, assignment in (("良い割り当て", GOOD_ASSIGNMENT),
                              ("予約を調査担当に戻す", BAD_ASSIGNMENT),
                              ("予約の担当が空", MISSING_ASSIGNMENT)):
        violations = check_assignment(TEAM_PLAN, assignment, registry)
        print(f"{label}: 違反 {len(violations)} 件 / 引き継ぎ "
              f"{handoff_count(TEAM_PLAN, assignment)} 回")
        for violation in violations:
            print(f"  - {violation}")

    print()
    print("=== 担当ごとのツール（許可リスト）===")
    for owner in GOOD_ASSIGNMENT:
        print(f"{owner}: {', '.join(tools_of(TEAM_PLAN, GOOD_ASSIGNMENT, owner))}")

    print()
    print("=== 分割の図（Mermaid）===")
    print(render_team_mermaid(TEAM_PLAN, GOOD_ASSIGNMENT))
    print()
    print("=== 計画そのものの DAG（S05 の mermaid_dag）===")
    print(mermaid_dag(TEAM_PLAN))


if __name__ == "__main__":
    main()
