#!/usr/bin/env python3
"""環境構築の最終確認：最初のエージェントを動かし、次に上限で止める。

同じシナリオを max_steps=8 と max_steps=2 で走らせ、stop_reason の違いを見る。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentkit.biztools import build_registry
from agentkit.llm import ScriptedClient
from agentkit.loop import ReActAgent


def show(traj) -> None:
    print(f"停止理由: {traj.stop_reason} / 手数: {len(traj.steps)} / "
          f"近似トークン(in/out): {traj.total_tokens['input']}/{traj.total_tokens['output']}")
    for step in traj.steps:
        names = ", ".join(c.name for c in step.calls) or "（最終回答）"
        print(f"  step {step.index}: {names}")
        for r in step.results:
            mark = "ok " if r.ok else "NG "
            body = (r.content if r.ok else (r.error or "")).splitlines()[:1]
            print(f"      {mark}{body[0][:60] if body else ''}")
    print(f"最終回答: {traj.final}")


print("=== 1回目：上限 8 ステップ（完了するはず）===")
agent = ReActAgent(ScriptedClient("expense_report"), build_registry(), max_steps=8)
show(agent.run("今月の経費レポートを作ってください", task_id="TASK-001"))

print("\n=== 2回目：上限 2 ステップ（途中で打ち切られるはず）===")
agent = ReActAgent(ScriptedClient("expense_report"), build_registry(), max_steps=2)
show(agent.run("今月の経費レポートを作ってください", task_id="TASK-002"))
