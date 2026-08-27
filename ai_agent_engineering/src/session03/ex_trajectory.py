#!/usr/bin/env python3
"""問題1の解答：ループを使わず、1周分の記録を手で組み立てて往復させる。

  docker compose exec app python src/session03/ex_trajectory.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.clock import FixedClock  # noqa: E402
from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: E402

CALL_ID = "manual-1-0"  # 依頼と結果を対応づける識別子。両方で同じ値を使う
POLICY = "経費精算: 領収書を添付し、支出日から10日以内に申請する。1件5万円以上は事前承認が必要。"

# ① 1周分の材料を作る（成功時は error を None にする）
call = ToolCall(call_id=CALL_ID, name="get_policy", args={"topic": "経費精算"})
result = ToolResult(call_id=CALL_ID, ok=True, content=POLICY, error=None)
step = Step(index=0, thought="まず経費精算の規程を確認する。",
            calls=[call], results=[result],
            usage={"input_tokens": 13, "output_tokens": 4})

# ② 軌跡に積み、どう終わったかを明示する
traj = Trajectory(task_id="TASK-manual", task="経費精算の規程を確認してください")
traj.steps.append(step)
traj.final = "規程を確認しました。"
traj.stop_reason = "done"

# ③ 保存して読み戻す（1行1ステップの JSONL）
out = ROOT / "traces" / "TASK-manual_ex01.jsonl"
traj.to_jsonl(out)
loaded = Trajectory.from_jsonl(out)

# ④ 目で確かめるのではなく assert で確かめる
assert loaded.task_id == traj.task_id
assert loaded.task == traj.task
assert loaded.stop_reason == "done"
assert loaded.final == traj.final
assert loaded.tool_names == ["get_policy"]
assert loaded.steps[0].thought == step.thought
assert loaded.steps[0].calls[0].call_id == loaded.steps[0].results[0].call_id
assert loaded.steps[0].results[0].error is None
assert loaded.total_tokens == {"input": 13, "output": 4}
# 日付が要るときも固定時計から取る（datetime.now() を直接呼ばない）
assert FixedClock().today() == "2026-08-15"

print(f"手数={len(loaded.steps)} ツール={loaded.tool_names} 停止理由={loaded.stop_reason}")
