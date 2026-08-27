"""状態と再開の軌跡テスト（pytest 版）。

  docker compose exec app python -m pytest src/session06 -q

`ScriptedClient` と `FixedClock` を使うので、何度実行しても同じ結果になる。
「動いた」ではなく「どの状態でどう終わったか」を機械判定するのが要点。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.state import Checkpoint  # noqa: E402
from durability import bookings_rows, fresh_dir, reset_data  # noqa: E402
from runner import ResumableRunner, SimulatedCrash  # noqa: E402
from scenarios import OUT_OF_ORDER, RESEARCH, STUCK  # noqa: E402
from states import build_machine  # noqa: E402

TASK = ("経費精算の規程を確認し、規程に照らして問題のある申請を洗い出して"
        "レポートにまとめ、報告会の会議室を予約してください")
TASK_ID = "TASK-006T"
DIR = ROOT / "traces" / "checkpoints" / "session06_test"
FULL_TOOLS = ["get_policy", "list_expenses", "search_docs", "write_file",
              "book_room", "book_room"]


@pytest.fixture(autouse=True)
def _clean():
    """毎回、業務データとチェックポイントを初期状態に戻す。"""
    reset_data()
    fresh_dir(DIR)
    yield
    reset_data()


def make(scenario, **kwargs) -> ResumableRunner:
    kwargs.setdefault("task_id", TASK_ID)
    kwargs.setdefault("checkpoint_dir", DIR)
    return ResumableRunner(ScriptedClient(scenario), build_registry(), **kwargs)


def test_状態機械のとおりに進んで完走する():
    runner = make(RESEARCH)
    traj = runner.run(TASK)
    assert traj.stop_reason == "done"
    assert runner.state.state == "done"
    assert traj.tool_names == FULL_TOOLS
    assert [s.usage["event"] for s in traj.steps][:3] == [
        "plan_ready", "need_more", "collected"]
    assert bookings_rows() == 1


def test_許されていない遷移は例外になる():
    machine = build_machine("collecting")
    with pytest.raises(ValueError, match="許可されていません"):
        machine.fire("booked")


def test_段階を飛ばしたツールは実行されない():
    runner = make(OUT_OF_ORDER, max_steps=4)
    traj = runner.run(TASK)
    assert not traj.steps[1].results[0].ok
    assert "この段階で使えるツール" in (traj.steps[1].results[0].error or "")
    assert bookings_rows() == 0


def test_同じ状態に留まり続けたら打ち切られる():
    runner = make(STUCK)
    traj = runner.run(TASK)
    assert traj.stop_reason == "loop_detected"
    assert runner.state.state == "failed"


def test_強制終了してもチェックポイントから同じ結果に到達する():
    with pytest.raises(SimulatedCrash):
        make(RESEARCH).run(TASK, crash_at=3)
    checkpoint = Checkpoint.load(TASK_ID, DIR)
    assert len(checkpoint.trajectory.steps) == 3
    assert checkpoint.state["state"] == "checking"

    traj = make(RESEARCH).run(TASK, resume=True)
    assert traj.stop_reason == "done"
    assert traj.tool_names == FULL_TOOLS
    assert bookings_rows() == 1  # 副作用は1回だけ


def test_保存の前に落ちても二重に予約しない():
    with pytest.raises(SimulatedCrash):
        make(RESEARCH, guard="ahead").run(TASK, crash_before_save=7)
    assert bookings_rows() == 1
    traj = make(RESEARCH, guard="ahead").run(TASK, resume=True)
    assert traj.stop_reason == "done"
    assert bookings_rows() == 1


def test_guard_なしだと保存前の落ち方で二重に予約する():
    with pytest.raises(SimulatedCrash):
        make(RESEARCH, guard="none").run(TASK, crash_before_save=7)
    make(RESEARCH, guard="none").run(TASK, resume=True)
    assert bookings_rows() == 2  # 軌跡は同じでも副作用は2回
