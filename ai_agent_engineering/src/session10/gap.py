#!/usr/bin/env python3
"""セッション10：素の `agentkit` に足りないものを、動かして確かめる。

`ReActAgent` は `awaiting_approval` で**止まる**ことはできる。
止まったあとが問題で、素のまま `resume` すると次の2つが起きる。

  1. 承認した操作が実行されないまま、モデルは「登録しました」と報告する
  2. 承認の要否をツール単位でしか判定しないので、3,200 円の申請でも止まる

ここで作る `TrustingGate` は**アンチパターン**の実装である（承認をツール名で
覚えてしまうゲート）。演習で「ずれ」を再現するために使う。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.approval import ApprovalGate  # noqa: E402
from agentkit.biztools import DATA, build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import ToolCall  # noqa: E402
from approval_scenarios import (EXPENSE_APPROVAL, SMALL_EXPENSE,  # noqa: E402
                                TASK, TASK_SMALL)
from gate import ReviewGate  # noqa: E402
from policy import decide  # noqa: E402


def reset_data() -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


def expense_rows() -> int:
    """副作用はデータ側で数える（軌跡だけでは分からない）。"""
    path = DATA / "expenses.jsonl"
    if not path.exists():
        return 0
    return sum(1 for line in path.open(encoding="utf-8") if line.strip())


class TrustingGate(ReviewGate):
    """アンチパターン：承認を「ツール名」で覚えてしまうゲート。

    一度 `submit_expense` を承認すると、以後どんな金額の `submit_expense` でも
    承認済みとみなす。承認内容と実行内容がずれても気づけない。
    """

    def check(self, call: ToolCall, traj=None) -> bool | None:
        for digest, approved in self.decisions.items():
            if self.requests.get(digest, {}).get("tool") == call.name:
                return approved
        return None


# ---------------------------------------------------------------------------
def naive_stop() -> dict:
    """素の `ReActAgent` でも「止まる」ことはできる。"""
    reset_data()
    gate = ApprovalGate(task_id="TASK-010N")
    agent = ReActAgent(ScriptedClient(EXPENSE_APPROVAL), build_registry(), approval=gate)
    traj = agent.run(TASK, task_id="TASK-010N")
    return {"stop_reason": traj.stop_reason,
            "ステップ数": len(traj.steps),
            "止まった操作": traj.steps[-1].calls[0].name,
            "そのステップのツール結果の数": len(traj.steps[-1].results),
            "expenses の行数": expense_rows()}


def naive_resume_bug() -> dict:
    """承認したのに実行されないまま「登録しました」と報告する。"""
    reset_data()
    gate = ApprovalGate(task_id="TASK-010N")
    client = ScriptedClient(EXPENSE_APPROVAL)
    agent = ReActAgent(client, build_registry(), approval=gate)
    traj = agent.run(TASK, task_id="TASK-010N")

    pending = traj.steps[-1].calls[0]
    gate.approve(pending)  # 人間が承認した
    resumed = agent.run(TASK, task_id="TASK-010N", resume=traj)
    return {"承認したか": gate.check(pending) is True,
            "stop_reason": resumed.stop_reason,
            "承認した操作のツール結果の数": len(resumed.steps[1].results),
            "expenses の行数": expense_rows(),
            "最終回答": resumed.final}


def blanket_approval() -> dict:
    """ツール単位の判定では、基準額未満の申請でも止まってしまう。"""
    reset_data()
    gate = ApprovalGate(task_id="TASK-010B")
    agent = ReActAgent(ScriptedClient(SMALL_EXPENSE), build_registry(), approval=gate)
    traj = agent.run(TASK_SMALL, task_id="TASK-010B")
    call = traj.steps[-1].calls[0]
    registry = build_registry()
    return {"ツール単位の判定（agentkit の既定）": traj.stop_reason,
            "止まった金額": call.args.get("amount"),
            "操作単位の判定（セッション10）": decide(call, registry.get(call.name)).mode,
            "expenses の行数": expense_rows()}


def drift_at_gate() -> dict:
    """同じツール・違う内容。ゲートの実装によって判定が変わる。"""
    approved = ToolCall("c1", "submit_expense",
                        {"employee": "高橋 涼", "amount": 68_000,
                         "category": "接待交際費", "note": "取引先との打ち合わせ",
                         "idempotency_key": "2026-08-15-EMP-003-68000"})
    drifted = ToolCall("c2", "submit_expense", {**approved.args, "amount": 148_000})

    trusting = TrustingGate("TASK-010T")
    trusting.audit.reset()
    trusting.request(approved, decide(approved))
    trusting.approve(approved, by="鈴木 彩")

    strict = ReviewGate("TASK-010S")
    strict.audit.reset()
    strict.request(approved, decide(approved))
    strict.approve(approved, by="鈴木 彩")

    return {"承認した金額": approved.args["amount"],
            "実行しようとした金額": drifted.args["amount"],
            "ツール名で覚える実装の判定": trusting.check(drifted),
            "ハッシュで固定する実装の判定": strict.check(drifted),
            "引数の順序を変えても同じ判定": strict.check(
                ToolCall("c3", "submit_expense",
                         dict(reversed(list(approved.args.items()))))) is True}


if __name__ == "__main__":
    for name, fn in (("① 止まることはできる", naive_stop),
                     ("② 素の再開は壊れている", naive_resume_bug),
                     ("③ ツール単位の判定は粗すぎる", blanket_approval),
                     ("④ 承認内容と実行内容のずれ", drift_at_gate)):
        print(f"--- {name} ---")
        for key, value in fn().items():
            print(f"  {key}: {value}")
    reset_data()
