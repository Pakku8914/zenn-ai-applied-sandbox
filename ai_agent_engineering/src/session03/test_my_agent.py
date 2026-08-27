"""自作ループの軌跡テスト（pytest 版）。

  docker compose exec app python -m pytest src/session03 -q

決定的なオラクル（ScriptedClient）を使うので、何度実行しても同じ結果になる。
「動いた」ではなく「どう終わったか」を機械判定するのがエージェントのテストの要点。
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
from agentkit.loop import Budget  # noqa: E402
from my_agent import MIXED_CALLS, ONE_STEP, PARALLEL_READS, MyReActAgent  # noqa: E402

TASK = "経費精算の規程を調べてください"


def run(scenario, *, max_steps: int = 8, on_limit: str = "fail",
        budget=None, parallel: bool = False):
    agent = MyReActAgent(ScriptedClient(scenario), build_registry(),
                         max_steps=max_steps, on_limit=on_limit,
                         budget=budget, parallel=parallel)
    return agent.run(TASK, task_id="TASK-test")


def test_1ステップで完了する():
    traj = run(ONE_STEP)
    assert traj.stop_reason == "done"
    assert len(traj.steps) == 1
    assert traj.tool_names == []
    assert traj.final == "1件5万円以上の経費は事前承認が必要です。"


def test_3ステップで失敗から回復する():
    traj = run("book_room_conflict")
    assert traj.stop_reason == "done"
    assert traj.tool_names == ["book_room", "book_room"]
    results = [r for s in traj.steps for r in s.results]
    assert results[0].ok is False
    assert "別の時間帯" in (results[0].error or "")
    assert results[1].ok is True


def test_上限に達したら成功として返さない():
    traj = run("max_steps_loop", max_steps=3)
    assert traj.stop_reason == "max_steps"
    assert len(traj.steps) == 3
    assert traj.final is None


@pytest.mark.parametrize(("on_limit", "marker"),
                         [("partial", "【未完了】"), ("handoff", "【要対応】")])
def test_上限到達時の振る舞いを選べる(on_limit, marker):
    traj = run("max_steps_loop", max_steps=3, on_limit=on_limit)
    # 振る舞いを変えても停止理由は max_steps のまま（done に化けさせない）
    assert traj.stop_reason == "max_steps"
    assert marker in (traj.final or "")


def test_予算上限で止まる():
    traj = run("max_steps_loop", max_steps=8, budget=Budget(max_tool_calls=2))
    assert traj.stop_reason == "budget"


def test_LLM_の失敗は_error_になる():
    class Broken:
        def respond(self, messages, tools):
            raise RuntimeError("接続が切れました")

    traj = MyReActAgent(Broken(), build_registry()).run(TASK, task_id="TASK-broken")
    assert traj.stop_reason == "error"
    assert "RuntimeError" in (traj.final or "")
    assert traj.steps == []


def test_軌跡が2回の実行で一致する():
    a, b = run("expense_report"), run("expense_report")
    assert a.tool_names == b.tool_names == ["get_policy", "list_expenses", "write_file"]
    assert a.final == b.final
    assert a.total_tokens == b.total_tokens


def test_会話履歴のIDが対応する():
    traj = run("expense_report")
    agent = MyReActAgent(ScriptedClient(ONE_STEP), build_registry())
    messages = agent.build_messages(TASK, traj)
    uses = [c["id"] for m in messages if isinstance(m["content"], list)
            for c in m["content"] if c.get("type") == "tool_use"]
    results = [c["tool_use_id"] for m in messages if isinstance(m["content"], list)
               for c in m["content"] if c.get("type") == "tool_result"]
    assert uses == results
    assert len(uses) == 3


def test_読み取りだけなら並列でも軌跡が変わらない():
    s = run(PARALLEL_READS, parallel=False)
    p = run(PARALLEL_READS, parallel=True)
    assert s.tool_names == p.tool_names
    assert s.final == p.final
    assert p.steps[0].usage["batch"] == "parallel"
    assert s.steps[0].usage["batch"] == "serial"
    # 結果の並びは呼び出しの並びと一致する（対応関係が崩れない）
    assert [r.call_id for r in p.steps[0].results] == [c.call_id for c in p.steps[0].calls]


def test_書き込みが混ざったら直列に落ちる():
    traj = run(MIXED_CALLS, parallel=True)
    assert traj.steps[0].usage["batch"] == "serial"
    assert traj.stop_reason == "done"
