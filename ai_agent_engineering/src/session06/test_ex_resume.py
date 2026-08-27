"""練習問題5の解答：落ちた場所を変えても、再開すれば同じ結果に到達すること。

  docker compose exec app python -m pytest src/session06/test_ex_resume.py -q

比べるのは4つだけ。ツール名の並び・遷移の並び・停止理由・副作用の回数。
最後の1つは軌跡に出ないので、データ側（bookings.jsonl の行数）で数える。
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
from scenarios import RESEARCH  # noqa: E402

TASK = ("経費精算の規程を確認し、規程に照らして問題のある申請を洗い出して"
        "レポートにまとめ、報告会の会議室を予約してください")
TASK_ID = "TASK-006X"
DIR = ROOT / "traces" / "checkpoints" / "session06_ex"


@pytest.fixture(autouse=True)
def _clean():
    reset_data()
    fresh_dir(DIR)
    yield
    reset_data()


def make() -> ResumableRunner:
    return ResumableRunner(ScriptedClient(RESEARCH), build_registry(),
                           task_id=TASK_ID, checkpoint_dir=DIR)


def summary(traj) -> dict:
    """比較の単位。軌跡から取れるものだけを並べる。"""
    return {"tools": traj.tool_names,
            "events": [s.usage.get("event", "") for s in traj.steps],
            "stop_reason": traj.stop_reason,
            "steps": len(traj.steps)}


@pytest.fixture(scope="module")
def baseline() -> dict:
    """落ちなかった場合の基準。副作用の回数も一緒に返す。"""
    reset_data()
    fresh_dir(DIR)
    traj = make().run(TASK)
    result = {**summary(traj), "bookings": bookings_rows()}
    reset_data()
    return result


@pytest.mark.parametrize("crash_at", [1, 3, 6])
def test_落ちた場所を変えても再開すれば同じ結果になる(crash_at, baseline):
    with pytest.raises(SimulatedCrash):
        make().run(TASK, crash_at=crash_at)
    checkpoint = Checkpoint.load(TASK_ID, DIR)
    assert len(checkpoint.trajectory.steps) == crash_at  # ステップ単位で保存している

    traj = make().run(TASK, resume=True)
    expected = {k: v for k, v in baseline.items() if k != "bookings"}
    assert summary(traj) == expected
    assert bookings_rows() == baseline["bookings"] == 1
