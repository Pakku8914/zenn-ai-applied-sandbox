#!/usr/bin/env python3
"""セッション10の軌跡テスト。

    python -m pytest src/session10 -q

承認は「人間が押すまで待つ」仕組みなので、実時間を待つテストにすると遅くて壊れやすい。
時計を注入し、承認・却下・条件付き承認を関数呼び出しで表現すると、承認フローが
まるごと決定的にテストできる。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from agentkit.approval import call_digest  # noqa: E402
from agentkit.biztools import DATA, build_registry  # noqa: E402
from agentkit.clock import JST, FixedClock  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from approval_runner import ApprovalRunner, inflate_amount, llm_calls  # noqa: E402
from approval_scenarios import (ALTERNATIVE, CONDITIONAL,  # noqa: E402
                                EXPENSE_APPROVAL, PII_SEND, SMALL_EXPENSE,
                                TASK, TASK_LEAK, TASK_SMALL)
from audit import AuditLog, tamper  # noqa: E402
from gate import ReviewGate  # noqa: E402
from policy import expense_key  # noqa: E402

DIR = ROOT / "traces" / "checkpoints" / "session10_test"


def reset_data() -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


def rows_of(name: str) -> list[dict]:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


@pytest.fixture(autouse=True)
def clean_state():
    """テストごとにデータとチェックポイントを初期状態に戻す。"""
    reset_data()
    shutil.rmtree(DIR, ignore_errors=True)
    DIR.mkdir(parents=True, exist_ok=True)
    yield
    reset_data()


def make(scenario, gate, *, task_id: str, **kwargs) -> ApprovalRunner:
    return ApprovalRunner(ScriptedClient(scenario), build_registry(), gate,
                          task_id=task_id, checkpoint_dir=DIR, **kwargs)


def new_gate(task_id: str, clock=None) -> ReviewGate:
    gate = ReviewGate(task_id, clock=clock)
    gate.audit.reset()
    return gate


def test_stops_before_the_side_effect():
    """5万円以上の申請は、実行される前に止まる。"""
    gate = new_gate("T1")
    runner = make(EXPENSE_APPROVAL, gate, task_id="T1")
    traj = runner.run(TASK)
    assert traj.stop_reason == "awaiting_approval"
    assert traj.steps[-1].calls[0].name == "submit_expense"
    assert traj.steps[-1].results == []          # 実行していない
    assert len(rows_of("expenses")) == 6         # データも増えていない


def test_resume_after_approval_costs_no_extra_llm_call():
    """承認を挟んでも手数は増えない（再開時にモデルに聞き直さない）。"""
    gate = new_gate("T2")
    runner = make(EXPENSE_APPROVAL, gate, task_id="T2")
    runner.run(TASK)
    gate.approve(runner.pending_call(), by="鈴木 彩")
    gate.save()
    done = make(EXPENSE_APPROVAL, ReviewGate.load("T2"), task_id="T2").run(TASK, resume=True)
    assert done.stop_reason == "done"
    assert llm_calls(done) == 3
    assert done.tool_names == ["get_policy", "submit_expense"]
    assert len(rows_of("expenses")) == 7
    assert rows_of("expenses")[-1]["amount"] == 68_000


def test_double_click_executes_once():
    """承認画面を二度押しても副作用は1回だけ。"""
    gate = new_gate("T3")
    runner = make(EXPENSE_APPROVAL, gate, task_id="T3")
    runner.run(TASK)
    gate.approve(runner.pending_call(), by="鈴木 彩")
    gate.save()
    for suffix in (".traj.jsonl", ".state.json"):
        shutil.copy2(DIR / f"T3{suffix}", DIR / f"T3{suffix}.bak")
    make(EXPENSE_APPROVAL, ReviewGate.load("T3"), task_id="T3").run(TASK, resume=True)
    assert len(rows_of("expenses")) == 7
    for suffix in (".traj.jsonl", ".state.json"):
        shutil.copy2(DIR / f"T3{suffix}.bak", DIR / f"T3{suffix}")
    again = make(EXPENSE_APPROVAL, ReviewGate.load("T3"), task_id="T3").run(TASK, resume=True)
    assert again.steps[1].usage["event"] == "already_done"
    assert len(rows_of("expenses")) == 7


def test_rejected_call_gets_a_reason_and_an_alternative():
    """却下されたら、理由がモデルに渡り、別の方法に切り替わる。"""
    gate = new_gate("T4")
    runner = make(ALTERNATIVE, gate, task_id="T4")
    runner.run(TASK)
    gate.reject(runner.pending_call(), by="鈴木 彩", reason="目的が不明")
    gate.save()
    done = make(ALTERNATIVE, ReviewGate.load("T4"), task_id="T4").run(TASK, resume=True)
    assert done.stop_reason == "done"
    assert "目的が不明" in (done.steps[0].results[0].error or "")
    assert done.tool_names == ["submit_expense", "write_file"]
    assert len(rows_of("expenses")) == 6


def test_abort_does_not_look_for_alternatives():
    """中止を選んだ場合は代替案を探さない。"""
    gate = new_gate("T5")
    runner = make(PII_SEND, gate, task_id="T5", on_reject="abort")
    traj = runner.run(TASK_LEAK)
    assert traj.steps[0].usage["mode"] == "dual"
    gate.reject(runner.pending_call(), by="伊藤 蓮", reason="規程違反")
    gate.save()
    done = make(PII_SEND, ReviewGate.load("T5"), task_id="T5",
                on_reject="abort").run(TASK_LEAK, resume=True)
    assert done.stop_reason == "error"
    assert len(done.steps) == 1
    assert rows_of("messages") == []


def test_conditional_approval_needs_a_new_idempotency_key():
    """金額を変えたら冪等キーも変わる（別の申請になる）。"""
    gate = new_gate("T6")
    runner = make(CONDITIONAL, gate, task_id="T6")
    runner.run(TASK)
    call = runner.pending_call()
    with pytest.raises(ValueError, match="idempotency_key"):
        gate.approve_with_changes(call, {"amount": 48_000}, by="鈴木 彩")
    gate.approve_with_changes(
        call, {"amount": 48_000, "idempotency_key": expense_key("EMP-003", 48_000)},
        by="鈴木 彩")
    gate.save()
    done = make(CONDITIONAL, ReviewGate.load("T6"), task_id="T6").run(TASK, resume=True)
    assert done.stop_reason == "done"
    assert rows_of("expenses")[-1]["amount"] == 48_000
    assert gate.check(call) is None  # 元の内容は承認されていない


def test_timeout_is_expressed_with_a_clock():
    """承認されないまま期限を過ぎたら諦める（実時間は待たない）。"""
    gate = new_gate("T7")
    runner = make(ALTERNATIVE, gate, task_id="T7")
    runner.run(TASK)
    gate.save()

    inside = ReviewGate.load("T7", clock=FixedClock(datetime(2026, 8, 15, 18, 0, tzinfo=JST)))
    still = make(ALTERNATIVE, inside, task_id="T7").run(TASK, resume=True)
    assert still.stop_reason == "awaiting_approval"

    outside = ReviewGate.load("T7", clock=FixedClock(datetime(2026, 8, 16, 10, 0, tzinfo=JST)))
    done = make(ALTERNATIVE, outside, task_id="T7").run(TASK, resume=True)
    assert done.steps[0].usage["event"] == "expired"
    assert done.stop_reason == "done"
    assert len(rows_of("expenses")) == 6
    assert outside.audit.events() == ["requested", "expired"]


def test_execution_must_match_what_was_approved():
    """実行直前に引数を組み立て直すと、ハッシュが合わずに止まる。"""
    gate = new_gate("T8")
    runner = make(EXPENSE_APPROVAL, gate, task_id="T8")
    runner.run(TASK)
    approved = runner.pending_call()
    gate.approve(approved, by="鈴木 彩")
    gate.save()
    done = make(EXPENSE_APPROVAL, ReviewGate.load("T8"), task_id="T8",
                rewrite=inflate_amount).run(TASK, resume=True)
    assert done.steps[1].usage["event"] == "mismatch"
    assert len(rows_of("expenses")) == 6
    assert gate.check(inflate_amount(approved)) is None
    assert call_digest(inflate_amount(approved)) != call_digest(approved)


def test_small_expense_is_not_blocked():
    """基準額未満は止めない。実行して記録を残す。"""
    gate = new_gate("T9")
    traj = make(SMALL_EXPENSE, gate, task_id="T9").run(TASK_SMALL)
    assert traj.stop_reason == "done"
    assert len(rows_of("expenses")) == 7
    assert gate.audit.events() == ["notified"]


def test_audit_log_detects_tampering():
    """監査ログの1行を書き換えると鎖が合わなくなる。"""
    log = AuditLog("T10")
    log.reset()
    log.append("requested", tool="submit_expense", mode="approve", detail="68,000 円")
    log.append("approved", actor="鈴木 彩", tool="submit_expense", mode="approve", detail="1/1")
    assert log.verify_chain() == (True, -1)
    tamper(log, 0, "3,200 円")
    assert log.verify_chain() == (False, 0)
    assert len(log.rows()) == 2
