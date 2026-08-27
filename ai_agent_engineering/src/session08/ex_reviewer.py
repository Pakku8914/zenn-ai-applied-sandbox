#!/usr/bin/env python3
"""練習問題6の解答：レビュー役を足して、増えた手数と変わらない成果物を測る。

「品質が心配だからレビュー役を置く」は最も多い分割の動機だが、
**レビュー役が成果物を変えないなら、それは手数を増やしただけ**である。
ここではその差を数える。

    python src/session08/ex_reviewer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.multi import Blackboard, Orchestrator  # noqa: E402
from compare import COLUMNS, row_of  # noqa: E402
from runners import (ROLE_TASKS, SCENARIOS, context_from_blackboard,  # noqa: E402
                     finish)
from sideeffects import reset_data  # noqa: E402
from workers import NEEDS, Ledger, Worker, format_handoff  # noqa: E402

# ツールを持たないレビュー役。読まずに「問題ありません」と言う（よくある姿）
REVIEWER = {
    "name": "s08_reviewer",
    "turns": [
        {"thought": "レポートの体裁を確認する。",
         "final": "レポートを確認しました。問題ありません。"},
    ],
}

# 実際にファイルを読むレビュー役。手数はさらに増える
REVIEWER_READING = {
    "name": "s08_reviewer_reading",
    "turns": [
        {"thought": "保存されたレポートを読んで確認する。",
         "calls": [{"name": "read_file", "args": {"path": "session08/report.md"}}]},
        {"thought": "内容を確認した。",
         "final": "レポートを確認しました。問題ありません。"},
    ],
}

TASKS = {**ROLE_TASKS, "reviewer": "保存された月次レポートの体裁を確認してください"}
NEEDS_EX = {**NEEDS, "reviewer": ("report_path",)}


def _run(label: str, order: list[str], workers: dict[str, Worker], ledger: Ledger) -> dict:
    """親が順に配るだけの実行器（`runners.run_orchestrator` の構造化版と同じ形）。"""
    orch = Orchestrator(workers=workers, blackboard=Blackboard())
    for i, role in enumerate(order, start=1):
        context = {} if i == 1 else context_from_blackboard(orch.blackboard, NEEDS_EX[role])
        if context:
            ledger.record_hop("親", role, context)
        orch.dispatch(role, format_handoff(TASKS[role], context), f"TASK-008R-{i:02d}")
        workers[role].publish(orch.blackboard)
    return finish(label, ledger, orch.trajectories, [[r] for r in order], orch.blackboard)


def build(order: list[str], ledger: Ledger, reviewer: dict) -> dict[str, Worker]:
    workers: dict[str, Worker] = {}
    for role in order:
        if role == "reviewer":
            allow = ["read_file"] if reviewer is REVIEWER_READING else []
            workers[role] = Worker(role, reviewer, ledger=ledger, allow=allow)
        else:
            workers[role] = Worker(role, SCENARIOS[role], ledger=ledger,
                                   analyze_after=(role == "analyst"))
    return workers


def run(label: str, order: list[str], reviewer: dict = REVIEWER) -> dict:
    reset_data()
    ledger = Ledger()
    return _run(label, order, build(order, ledger, reviewer), ledger)


BASE_ORDER = ["collector", "analyst", "writer", "notifier"]
WITH_REVIEWER = ["collector", "analyst", "writer", "reviewer", "notifier"]


def rows() -> list[dict]:
    return [
        run("オーケストレータ（構造化）", BASE_ORDER),
        run("＋レビュー役（読まない）", WITH_REVIEWER),
        run("＋レビュー役（実際に読む）", WITH_REVIEWER, REVIEWER_READING),
    ]


def render(results: list[dict]) -> str:
    return "\n".join([" | ".join(COLUMNS)] + [" | ".join(row_of(r)) for r in results])


def main() -> None:
    results = rows()
    print(render(results))
    print()
    same = all(r["report"] == results[0]["report"] for r in results)
    print(f"3通りの成果物は同一か: {same}")
    reset_data()


if __name__ == "__main__":
    main()
