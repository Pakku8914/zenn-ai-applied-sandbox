#!/usr/bin/env python3
"""セッション11の自己検証：障害注入・冪等性・循環検出。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentkit.biztools import DATA, build_registry, submit_expense  # noqa: E402
from agentkit.llm import FlakyClient, ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.tools import ToolError  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def expense_count() -> int:
    path = DATA / "expenses.jsonl"
    return sum(1 for line in path.open(encoding="utf-8") if line.strip())


def reset_data() -> None:
    import subprocess

    subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "tools" / "make_data.py")],
                   check=True, capture_output=True)


# --- 障害注入：再試行が無いと失敗で終わる ----------------------------------
reset_data()
llm = FlakyClient(ScriptedClient("expense_report"), fail_on=(2,), mode="exception")
traj = ReActAgent(llm, build_registry(), max_steps=8).run("経費レポート", task_id="TASK-flaky")
check("障害注入で error として終わる", traj.stop_reason == "error", f"stop_reason={traj.stop_reason}")
check("失敗の内容が軌跡に残る", "失敗" in (traj.final or ""), (traj.final or "")[:60])

# --- 冪等性：同じ内容を2回申請すると2件になる（既定の実装の欠け）----------
reset_data()
before = expense_count()
submit_expense("佐藤 健", 3000, "交通費", "往復", idempotency_key="KEY-1")
submit_expense("佐藤 健", 3000, "交通費", "往復", idempotency_key="KEY-1")
after = expense_count()
check("既定の submit_expense は冪等でない（2件になる）", after - before == 2,
      f"{before} -> {after}")


# --- 冪等化：キーで重複を弾く実装を足すと1件になる --------------------------
def submit_expense_idempotent(employee: str, amount: int, category: str,
                              note: str = "", idempotency_key: str = "") -> str:
    """セッション11で読者が実装する冪等版（ここでは参照解として置く）。"""
    if not idempotency_key:
        raise ToolError("idempotency_key を指定してください（再送の重複を防ぐため）。")
    rows = [json.loads(line) for line in (DATA / "expenses.jsonl").open(encoding="utf-8")
            if line.strip()]
    existing = next((r for r in rows if r.get("idempotency_key") == idempotency_key), None)
    if existing:
        return f"{existing['expense_id']} は既に申請済みです（重複申請を防ぎました）。"
    return submit_expense(employee, amount, category, note, idempotency_key)


reset_data()
before = expense_count()
submit_expense_idempotent("佐藤 健", 3000, "交通費", "往復", idempotency_key="KEY-2")
msg = submit_expense_idempotent("佐藤 健", 3000, "交通費", "往復", idempotency_key="KEY-2")
after = expense_count()
check("冪等化すると2回呼んでも1件", after - before == 1, f"{before} -> {after}")
check("2回目は重複を検出したと分かる", "既に申請済み" in msg, msg)

# --- 循環検出：同じツール・同じ引数の連続を検出する ------------------------
reset_data()
traj = ReActAgent(ScriptedClient("max_steps_loop"), build_registry(), max_steps=6).run(
    "経費の規程を調べる", task_id="TASK-loop")


def detect_loop(trajectory, window: int = 3) -> bool:
    """同じ (ツール名, 引数) が window 回連続したら循環と見なす。"""
    seen: list[tuple] = []
    for step in trajectory.steps:
        for call in step.calls:
            key = (call.name, json.dumps(call.args, ensure_ascii=False, sort_keys=True))
            seen.append(key)
            if len(seen) >= window and len(set(seen[-window:])) == 1:
                return True
    return False


check("循環を検出できる", detect_loop(traj), f"tool_names={traj.tool_names}")
check("上限にも達している", traj.stop_reason == "max_steps", f"stop_reason={traj.stop_reason}")

# --- 一時的失敗と恒久的失敗の区別 ------------------------------------------
reset_data()
registry = build_registry()
from agentkit.models import ToolCall  # noqa: E402

conflict = registry.call(ToolCall("c1", "book_room", {"room": "みなと", "start": "10:00"}))
notfound = registry.call(ToolCall("c2", "book_room", {"room": "存在しない部屋", "start": "11:00"}))
check("競合は再試行の手がかりを含む（一時的）", "別の時間帯" in (conflict.error or ""))
check("存在しない会議室は選択肢を示す（恒久的）",
      "指定できる会議室" in (notfound.error or ""), (notfound.error or "")[:60])

reset_data()
if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション11の検証はすべて成功しました。")
