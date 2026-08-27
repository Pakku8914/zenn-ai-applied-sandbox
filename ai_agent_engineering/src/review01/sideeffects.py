#!/usr/bin/env python3
"""軌跡が同じでも、データに残るものは同じではない（S03 × S04）。

    docker compose exec app python src/review01/sideeffects.py

モデルの応答（`traces.SAME_RESPONSES`）を固定したまま、道具側だけを差し替える。

  検証なし … スキーマは同じだが引数を検証しない。実装は冪等でない `submit_expense`
  検証あり … 同じスキーマで引数を検証する。実装は冪等な `submit_expense_once`

手数・停止理由・失敗モードはどちらも同じになる。違うのは `expenses.jsonl` に
残った行数と区分である。**軌跡だけを見ていると気づけない事故**がここにある。
"""

from __future__ import annotations

import json

from _paths import setup

ROOT = setup()

from agentkit.biztools import DATA  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402

from failure_modes import classify  # noqa: E402  (src/session02)
from goodtools import build_good_registry, build_unchecked_registry  # noqa: E402
from measure import reset_data, row_count  # noqa: E402
from traces import SAME_RESPONSES, SUBMIT_TASK  # noqa: E402

CONDITIONS = (
    ("検証なし", build_unchecked_registry, "TASK-R01-U"),
    ("検証あり", build_good_registry, "TASK-R01-V"),
)


def _categories(start: int) -> list[str]:
    """`start` 行目以降（＝この実行で増えた分）の区分を返す。"""
    rows = [json.loads(line)
            for line in (DATA / "expenses.jsonl").open(encoding="utf-8") if line.strip()]
    return [row["category"] for row in rows[start:]]


def run_pair() -> dict:
    """同じ応答を2つの条件で走らせ、軌跡とデータの両方を記録する。"""
    out: dict = {}
    for label, factory, task_id in CONDITIONS:
        reset_data()
        before = row_count()
        registry = factory()
        traj = ReActAgent(ScriptedClient(SAME_RESPONSES), registry,
                          max_steps=4).run(SUBMIT_TASK, task_id=task_id)
        out[label] = {
            "steps": len(traj.steps),
            "tools": traj.tool_names,
            "ok_calls": sum(1 for step in traj.steps for r in step.results if r.ok),
            "stop_reason": traj.stop_reason,
            "added": row_count() - before,
            "categories": _categories(before),
            "modes": classify(traj, allowed_tools={"submit_expense"}, registry=registry),
        }
    reset_data()
    return out


def main() -> None:
    print("=== 同じモデル応答・同じツール名で、道具側だけを差し替える ===")
    print("条件 | 手数 | 呼び出し | 成功 | 停止理由 | 失敗モード | 増えた行 | 残った区分")
    pair = run_pair()
    for label, _factory, _task_id in CONDITIONS:
        row = pair[label]
        print(f"{label} | {row['steps']} | {len(row['tools'])} | {row['ok_calls']} | "
              f"{row['stop_reason']} | {', '.join(row['modes'])} | {row['added']} | "
              f"{', '.join(row['categories'])}")
    print("\n軌跡（手数・停止理由・失敗モード）は一致するのに、"
          "残ったデータは一致しない。")


if __name__ == "__main__":
    main()
