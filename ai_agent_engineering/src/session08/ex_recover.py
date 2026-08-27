#!/usr/bin/env python3
"""練習問題9の解答：上流で落ちた事実を、下流が権限を使って取り直す。

収集係が規程名を間違えて `get_policy` を空振りさせると、判定基準（5万円）が
下流に届かない。届かなければ違反の判定はできない。
**下流が取り直せるのは、下流にその権限があるときだけ**である。
権限を広げるか、上流を直すか——この選択を数字で見る。

    python src/session08/ex_recover.py
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

ORDER = ["collector", "analyst", "writer", "notifier"]

# 規程名を間違えて空振りする収集係（`get_policy` は ToolError になる）
COLLECTOR_BROKEN = {
    "name": "s08_collector_broken",
    "turns": [
        {"thought": "旅費規程を読む。",
         "calls": [{"name": "get_policy", "args": {"topic": "旅費規程"}}]},
        {"thought": "経費申請の一覧を取る。",
         "calls": [{"name": "list_expenses", "args": {"status": "all"}}]},
        {"thought": "集めたので次の担当へ渡す。",
         "final": "経費申請を 6 件確認しました。合計は 285,400 円です。"},
    ],
}

# 判定基準が届いていないことに気づいて、自分で取り直す集計係
ANALYST_RECOVER = {
    "name": "s08_analyst_recover",
    "turns": [
        {"thought": "判定基準が引き継がれていない。規程を自分で読む。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "基準が分かったので判定する。",
         "final": "区分別に集計しました。合計 285,400 円、6 件です。"
                  "基準額以上で未承認の申請を洗い出しました。"},
    ],
}


def run(label: str, *, recover: bool) -> dict:
    reset_data()
    ledger = Ledger()
    workers = {
        "collector": Worker("collector", COLLECTOR_BROKEN, ledger=ledger),
        "analyst": Worker("analyst",
                          ANALYST_RECOVER if recover else SCENARIOS["analyst"],
                          ledger=ledger, analyze_after=True,
                          allow=["get_policy"] if recover else []),
        "writer": Worker("writer", SCENARIOS["writer"], ledger=ledger),
        "notifier": Worker("notifier", SCENARIOS["notifier"], ledger=ledger),
    }
    orch = Orchestrator(workers=workers, blackboard=Blackboard())
    for i, role in enumerate(ORDER, start=1):
        context = {} if i == 1 else context_from_blackboard(orch.blackboard, NEEDS[role])
        if context:
            ledger.record_hop("親", role, context)
        orch.dispatch(role, format_handoff(ROLE_TASKS[role], context),
                      f"TASK-008V-{i:02d}")
        workers[role].publish(orch.blackboard)
    result = finish(label, ledger, orch.trajectories, [[r] for r in ORDER],
                    orch.blackboard)
    result["threshold"] = workers["analyst"].facts.get("threshold")
    return result


def rows() -> list[dict]:
    return [run("上流が空振り（取り直さない）", recover=False),
            run("上流が空振り（集計係が取り直す）", recover=True)]


def render(results: list[dict]) -> str:
    return "\n".join([" | ".join(COLUMNS)] + [" | ".join(row_of(r)) for r in results])


def main() -> None:
    results = rows()
    print(render(results))
    print()
    for r in results:
        print(f"{r['方式']}: 集計係が持てた判定基準={r['threshold']} "
              f"欠け={r['score']['missing']}")
    reset_data()


if __name__ == "__main__":
    main()
