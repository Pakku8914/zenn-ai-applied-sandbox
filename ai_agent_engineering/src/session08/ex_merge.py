#!/usr/bin/env python3
"""練習問題8の解答：役を統合して段数と引き継ぎを減らす。

分割の練習ばかりしていると忘れがちだが、**役を減らす**のも設計変更である。
集計係と執筆係は同じ事実（集計結果）しか扱わない。1体にまとめると、
手数・段数・引き継ぎ項目のすべてが減り、成果物は変わらない。

失うものは1つある。生データ（`expenses`）と書き込み権限（`write_file`）が
同じ文脈に同居することである。この取引を数字で見て判断する。

    python src/session08/ex_merge.py
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.multi import Blackboard, Orchestrator  # noqa: E402
from compare import COLUMNS, row_of  # noqa: E402
from runners import (ROLE_TASKS, SCENARIOS, context_from_blackboard,  # noqa: E402
                     finish, run_orchestrator_parallel)
from sideeffects import reset_data  # noqa: E402
from workers import NEEDS, PRODUCES, Ledger, Worker, format_handoff  # noqa: E402

# 集計と執筆を1体でやる。集計は決定的に導けるのでツールは書き込み1つだけ
ANALYST_WRITER = {
    "name": "s08_analyst_writer",
    "turns": [
        {"thought": "受け取った申請を区分ごとに集計し、違反を洗い出してレポートに保存する。",
         "calls": [{"name": "write_file",
                    "args": {"path": "session08/report.md", "content": "__REPORT__"}}]},
        {"thought": "保存できた。",
         "final": "集計して workspace/session08/report.md に保存しました。"},
    ],
}

FIRST = ["policy_collector", "expense_collector"]
REST = ["analyst_writer", "notifier"]

TASKS = {**ROLE_TASKS,
         "analyst_writer": "受け取った経費申請を区分ごとに集計し、基準額以上で未承認の申請を"
                           "注記した月次レポートを session08/report.md に保存してください"}
NEEDS_EX = {**NEEDS, "analyst_writer": ("expenses", "threshold")}
PRODUCES_EX = {**PRODUCES,
               "analyst_writer": ("by_category", "total", "count", "violations",
                                  "report_path")}


def run_merged() -> dict:
    """収集2体を並列に走らせ、集計執筆を1体で受ける。"""
    reset_data()
    ledger = Ledger()
    workers = {role: Worker(role, SCENARIOS[role], ledger=ledger) for role in FIRST}
    workers["analyst_writer"] = Worker("analyst_writer", ANALYST_WRITER, ledger=ledger,
                                       allow=["write_file"], analyze_after=True)
    workers["notifier"] = Worker("notifier", SCENARIOS["notifier"], ledger=ledger)
    orch = Orchestrator(workers=workers, blackboard=Blackboard())

    with ThreadPoolExecutor(max_workers=len(FIRST)) as pool:
        futures = [pool.submit(workers[role].run, TASKS[role], f"TASK-008M-{i:02d}")
                   for i, role in enumerate(FIRST, start=1)]
        trajectories = [f.result() for f in futures]

    # 書き込み順は固定する（並列のまま書くと latest の指す値がぶれる）
    for role, traj in zip(FIRST, trajectories):
        orch.trajectories[role] = traj
        orch.blackboard.write(role, "result", traj.final or "")
        workers[role].publish(orch.blackboard, keys=PRODUCES_EX.get(role))

    for i, role in enumerate(REST, start=len(FIRST) + 1):
        context = context_from_blackboard(orch.blackboard, NEEDS_EX[role])
        if context:
            ledger.record_hop("親", role, context)
        orch.dispatch(role, format_handoff(TASKS[role], context), f"TASK-008M-{i:02d}")
        workers[role].publish(orch.blackboard, keys=PRODUCES_EX.get(role))

    return finish("並列＋集計執筆を統合", ledger, orch.trajectories,
                  [FIRST] + [[r] for r in REST], orch.blackboard)


def rows() -> list[dict]:
    return [run_orchestrator_parallel(), run_merged()]


def render(results: list[dict]) -> str:
    return "\n".join([" | ".join(COLUMNS)] + [" | ".join(row_of(r)) for r in results])


def main() -> None:
    results = rows()
    print(render(results))
    print()
    print(f"成果物は同一か: {results[0]['report'] == results[1]['report']}")
    reset_data()


if __name__ == "__main__":
    main()
