"""信頼性設計の軌跡テスト（pytest 版）。

  docker compose exec app python -m pytest src/session11 -q

`ScriptedClient` と `FixedClock`、そして `RecordingSleeper` を使うので、
何度実行しても同じ結果になる（実時間では1秒も待たない）。
副作用の回数は軌跡ではなく `data/` の行数で数える。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from agentkit.biztools import book_room, build_registry, send_message  # noqa: E402
from agentkit.clock import StepClock  # noqa: E402
from agentkit.llm import FlakyClient, ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import ToolCall  # noqa: E402
from agentkit.tools import ToolError  # noqa: E402
from backoff import backoff_delay  # noqa: E402
from compensate import (Action, Saga, cancel_booking,  # noqa: E402
                        cancel_expense_by_key)
from failure_kinds import (HANDOFF, PARTIAL, PERMANENT, RETRY_ALTERED,  # noqa: E402
                           RETRY_SAME, TRANSIENT, classify_error, retry_decision)
from faults import CHAT_MESSAGE, FaultInjector  # noqa: E402
from guards import RunLimits, detect_alternating, detect_loop  # noqa: E402
from idempotency import (active_expenses, build_registry_with_flaky_submit,  # noqa: E402
                         build_submit_registry, count_rows, expense_key,
                         submit_expense_once)
from retry_runner import (ReliableRunner, llm_calls, retry_blindly,  # noqa: E402
                          retry_guarded)
from retry_scenarios import (EXPENSE_SUBMIT, LOOP_ALTERNATING,  # noqa: E402
                             TASK_BOOK, TASK_SUBMIT)

CONFLICT = ("みなと の 10:00 は既に予約されています。別の時間帯（例: 11:00）"
            "または別の会議室を指定してください。")
NO_REPLY = ("経費システムから応答が返りませんでした（タイムアウト）。"
            "申請が登録されたかどうかは確認できません。")
CONNECT = ("経費システムに接続できませんでした（一時的な障害）。"
           "しばらく待ってから同じ内容で再実行してください。")
SUBMIT_ARGS = {"employee": "高橋 涼", "amount": 68_000, "category": "接待交際費",
               "note": "取引先との打ち合わせ",
               "idempotency_key": expense_key("EMP-003", 68_000)}
SUBMIT_CALL = ToolCall("test-submit", "submit_expense", SUBMIT_ARGS)


def reset_data() -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


@pytest.fixture(autouse=True)
def _clean():
    """毎回、業務データを初期状態に戻す（副作用を出す演習だから必須）。"""
    reset_data()
    yield
    reset_data()


# --- 失敗の切り分け ---------------------------------------------------------
@pytest.mark.parametrize("message,kind", [
    (CONFLICT, PERMANENT),
    (CONNECT, TRANSIENT),
    (NO_REPLY, PARTIAL),
])
def test_classify(message, kind):
    assert classify_error(message) == kind


@pytest.mark.parametrize("message,idempotent,action", [
    (CONFLICT, False, RETRY_ALTERED),   # 引数を変えれば通る
    (CONNECT, True, RETRY_SAME),        # 冪等なら同じ引数で再試行してよい
    (CONNECT, False, HANDOFF),          # 冪等でないなら再送しない
    (NO_REPLY, True, RETRY_SAME),
    (NO_REPLY, False, HANDOFF),         # ここが二重申請の分かれ道
])
def test_retry_decision(message, idempotent, action):
    assert retry_decision(message, idempotent=idempotent).action == action


def test_backoff_is_capped():
    assert [backoff_delay(i) for i in range(6)] == [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]


# --- 再試行の有無で完走が変わる ---------------------------------------------
def test_plain_agent_stops_on_transient_failure():
    flaky = FlakyClient(ScriptedClient(EXPENSE_SUBMIT), fail_on=(3,))
    traj = ReActAgent(flaky, build_registry(), max_steps=8).run(TASK_SUBMIT)
    assert traj.stop_reason == "error"
    assert flaky.count == 3


def test_retry_recovers_and_counts_the_extra_call():
    flaky = FlakyClient(ScriptedClient(EXPENSE_SUBMIT), fail_on=(3,))
    runner = ReliableRunner(flaky, build_registry(), max_retries=1)
    traj = runner.run(TASK_SUBMIT)
    assert traj.stop_reason == "done"
    assert flaky.count == 4               # 再試行のぶん1回増える
    assert llm_calls(traj) == 4           # 手数にも数える
    assert runner.sleeper.total == 0.5    # 実時間では待っていない


def test_retry_limit_is_respected():
    flaky = FlakyClient(ScriptedClient(EXPENSE_SUBMIT), fail_on=(3, 4))
    traj = ReliableRunner(flaky, build_registry(), max_retries=1).run(TASK_SUBMIT)
    assert traj.stop_reason == "error"
    assert flaky.count == 4


# --- 冪等性 -----------------------------------------------------------------
def test_blind_retry_creates_duplicate():
    registry = build_submit_registry(idempotent=False)
    before = count_rows("expenses")
    result, attempts, _ = retry_blindly(registry, SUBMIT_CALL, max_retries=1)
    assert result.ok and attempts == 2
    assert count_rows("expenses") - before == 2   # 二重申請


def test_guarded_retry_refuses_non_idempotent():
    registry = build_submit_registry(idempotent=False)
    before = count_rows("expenses")
    result, attempts, _ = retry_guarded(registry, SUBMIT_CALL, max_retries=1)
    assert not result.ok and attempts == 1
    assert "人の確認が必要" in (result.error or "")
    assert count_rows("expenses") - before == 1


def test_idempotency_key_absorbs_the_retry():
    registry = build_submit_registry(idempotent=True)
    before = count_rows("expenses")
    result, attempts, _ = retry_guarded(registry, SUBMIT_CALL, max_retries=1)
    assert result.ok and attempts == 2
    assert count_rows("expenses") - before == 1


# --- 循環と上限 -------------------------------------------------------------
def test_loop_detection_stops_earlier_than_max_steps():
    with_loop = ReliableRunner(ScriptedClient("max_steps_loop"), build_registry(),
                               limits=RunLimits(max_steps=6),
                               loop_window=3).run("経費の規程を調べてください")
    assert with_loop.stop_reason == "loop_detected"
    assert len(with_loop.steps) == 3


def test_alternating_loop_is_detected():
    traj = ReliableRunner(ScriptedClient(LOOP_ALTERNATING), build_registry(),
                          limits=RunLimits(max_steps=6)).run(TASK_BOOK)
    assert traj.stop_reason == "loop_detected"
    assert len(traj.steps) == 4
    assert detect_alternating([f"book_room:{i % 2}" for i in range(4)])
    assert not detect_loop(["a", "b", "c"])


def test_time_limit_uses_injected_clock():
    traj = ReliableRunner(ScriptedClient("expense_report"), build_registry(),
                          limits=RunLimits(deadline_seconds=90),
                          clock=StepClock(step_seconds=30)).run(
        "2026年8月の経費レポートを作成してください")
    assert traj.stop_reason == "budget"
    assert len(traj.steps) == 2


# --- 失敗の伝え方と補償 -----------------------------------------------------
def test_unverified_effect_is_not_reported_as_done():
    registry = build_registry_with_flaky_submit(idempotent=False, fail_on=(1,),
                                                when="after")
    before = count_rows("expenses")
    traj = ReliableRunner(ScriptedClient(EXPENSE_SUBMIT), registry,
                          max_retries=1).run(TASK_SUBMIT)
    assert traj.stop_reason == "error"          # モデルは「登録しました」と言っている
    assert count_rows("expenses") - before == 1
    assert "実行されたか分からない操作" in (traj.final or "")
    assert expense_key("EMP-003", 68_000) in (traj.final or "")


def test_saga_compensates_in_reverse_order():
    key = expense_key("EMP-003", 12_000)
    broken = FaultInjector(send_message, fail_on=(1,), when="before",
                           message=CHAT_MESSAGE)
    result = Saga().run([
        Action("会議室を予約", lambda: book_room("うみかぜ", "10:00", 60),
               lambda: cancel_booking("うみかぜ", "10:00")),
        Action("経費を申請",
               lambda: submit_expense_once("高橋 涼", 12_000, "備品",
                                           idempotency_key=key),
               lambda: cancel_expense_by_key(key)),
        Action("参加者へ連絡",
               lambda: broken(to="EMP-003", body="報告会は10時からです。")),
    ])
    assert not result.ok
    assert result.compensated == ["経費を申請", "会議室を予約"]
    assert count_rows("bookings") == 0
    assert count_rows("messages") == 0
    assert active_expenses() == 6          # 有効な申請は元に戻る
    assert count_rows("expenses") == 7     # ただし取り消しの記録は残る


def test_compensation_is_idempotent():
    key = expense_key("EMP-003", 12_000)
    submit_expense_once("高橋 涼", 12_000, "備品", idempotency_key=key)
    assert "取り消しました" in cancel_expense_by_key(key)
    assert "打ち消す申請はありません" in cancel_expense_by_key(key)
    with pytest.raises(ToolError):
        cancel_expense_by_key("")
