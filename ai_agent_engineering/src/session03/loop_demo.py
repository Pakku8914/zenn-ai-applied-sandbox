#!/usr/bin/env python3
"""セッション3の本文で使う実行例。停止理由の違いを並べて見る。

  docker compose exec app python src/session03/loop_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from my_agent import ONE_STEP, PARALLEL_READS, MyReActAgent, render_trace  # noqa: E402

TASK_LIMIT = "経費精算の規程を調べてください"


def head(title: str) -> None:
    print(f"\n=== {title} ===")


head("A 1ステップで終わる（停止理由 done）")
agent = MyReActAgent(ScriptedClient(ONE_STEP), build_registry(), max_steps=8)
print(render_trace(agent.run("5万円以上の経費に承認は必要ですか", task_id="TASK-oneshot")))

head("B 3ステップかかる（1手目が失敗してから回復する）")
agent = MyReActAgent(ScriptedClient("book_room_conflict"), build_registry(), max_steps=8)
print(render_trace(agent.run("みなと会議室を10時から1時間押さえてください", task_id="TASK-room")))

head("C 上限に達する — on_limit='fail'（失敗として返す）")
agent = MyReActAgent(ScriptedClient("max_steps_loop"), build_registry(),
                     max_steps=3, on_limit="fail")
print(render_trace(agent.run(TASK_LIMIT, task_id="TASK-limit-fail")))

head("D 上限に達する — on_limit='partial'（途中結果を返す）")
agent = MyReActAgent(ScriptedClient("max_steps_loop"), build_registry(),
                     max_steps=3, on_limit="partial")
traj = agent.run(TASK_LIMIT, task_id="TASK-limit-partial")
print(render_trace(traj, show_final=False))
print("--- final ---")
print(traj.final)

head("E 上限に達する — on_limit='handoff'（人間に渡す）")
agent = MyReActAgent(ScriptedClient("max_steps_loop"), build_registry(),
                     max_steps=3, on_limit="handoff")
traj = agent.run(TASK_LIMIT, task_id="TASK-limit-handoff")
print(render_trace(traj, show_final=False))
print("--- final ---")
print(traj.final)

head("F 読み取り3本を並列で呼ぶ（軌跡は直列と一致する）")
serial = MyReActAgent(ScriptedClient(PARALLEL_READS), build_registry(), parallel=False)
parallel = MyReActAgent(ScriptedClient(PARALLEL_READS), build_registry(), parallel=True)
t_serial = serial.run("材料を集めてください", task_id="TASK-serial")
t_parallel = parallel.run("材料を集めてください", task_id="TASK-parallel")
print(render_trace(t_parallel))
print(f"直列と並列でツールの並びが一致: {t_serial.tool_names == t_parallel.tool_names}")
print(f"直列と並列で最終回答が一致: {t_serial.final == t_parallel.final}")
