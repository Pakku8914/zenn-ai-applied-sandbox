#!/usr/bin/env python3
"""セッション3の自己検証：ループが決定的に動き、停止条件が正しく効くこと。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import Budget, ReActAgent  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def run(scenario: str, *, max_steps: int = 8, budget: Budget | None = None) -> Trajectory:
    agent = ReActAgent(ScriptedClient(scenario), build_registry(),
                       max_steps=max_steps, budget=budget)
    return agent.run("経費レポートを作成してください", task_id=f"TASK-{scenario}")


# --- 正常系：完了して stop_reason が done になる ---------------------------
t1 = run("expense_report")
check("正常系が完了する", t1.stop_reason == "done", f"stop_reason={t1.stop_reason}")
check("ツール呼び出しの順序が期待どおり",
      t1.tool_names == ["get_policy", "list_expenses", "write_file"],
      str(t1.tool_names))
check("最終回答が入っている", bool(t1.final), (t1.final or "")[:40])
check("全ステップでツール結果が成功", all(r.ok for s in t1.steps for r in s.results))

# --- 決定性：2回走らせて同じ軌跡になる -------------------------------------
t1b = run("expense_report")
check("2回実行して軌跡が一致する", t1.tool_names == t1b.tool_names and t1.final == t1b.final)

# --- 上限：ステップ上限に達したら max_steps で止まる -----------------------
t2 = run("max_steps_loop", max_steps=3)
check("ステップ上限で止まる", t2.stop_reason == "max_steps", f"stop_reason={t2.stop_reason}")
check("上限を超えてステップを積まない", len(t2.steps) == 3, f"steps={len(t2.steps)}")
check("上限到達時に final を成功として埋めない", t2.final is None)

# --- 予算：上限を超えたら budget で止まる ----------------------------------
t3 = run("max_steps_loop", max_steps=8, budget=Budget(max_tool_calls=2))
check("予算上限で止まる", t3.stop_reason == "budget", f"stop_reason={t3.stop_reason}")

# --- ツール失敗：失敗結果を渡してループが続く ------------------------------
t4 = run("book_room_conflict")
first_results = [r for s in t4.steps for r in s.results]
check("1回目の予約が失敗している", not first_results[0].ok, first_results[0].error or "")
check("失敗後もループが続いて完了する", t4.stop_reason == "done", f"stop_reason={t4.stop_reason}")
check("エラーメッセージが次の行動の手がかりを含む",
      "別の時間帯" in (first_results[0].error or ""))

# --- 存在しないツール：例外にせずツール名を教える --------------------------
from agentkit.models import ToolCall  # noqa: E402

res = build_registry().call(ToolCall("c1", "no_such_tool", {}))
check("未登録ツールでも例外にならない", not res.ok and "存在しません" in (res.error or ""))
check("使えるツール名を提示する", "search_docs" in (res.error or ""))

# --- 軌跡の保存と読み込みが往復する ---------------------------------------
out = Path(__file__).resolve().parents[2] / "traces" / "verify_s03.jsonl"
t1.to_jsonl(out)
loaded = Trajectory.from_jsonl(out)
check("軌跡が保存・読み込みで往復する",
      loaded.tool_names == t1.tool_names and loaded.stop_reason == t1.stop_reason)
out.unlink(missing_ok=True)

# --- 会話履歴の組み立て：ツール結果が対応づく -----------------------------
agent = ReActAgent(ScriptedClient("expense_report"), build_registry())
messages = agent._rebuild_messages("タスク", t1)
tool_use_ids = [c["id"] for m in messages if isinstance(m["content"], list)
                for c in m["content"] if c.get("type") == "tool_use"]
tool_result_ids = [c["tool_use_id"] for m in messages if isinstance(m["content"], list)
                   for c in m["content"] if c.get("type") == "tool_result"]
check("tool_use と tool_result の id が一致する", tool_use_ids == tool_result_ids,
      f"{len(tool_use_ids)} 組")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション3の検証はすべて成功しました。")
