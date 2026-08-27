"""計画・分解・再計画の軌跡テスト（pytest 版）。

    docker compose exec app python -m pytest src/session05 -q

`pytest` 単体では実行しない（pytest.ini の testpaths に tests/ が含まれるため）。
決定的なオラクル（ScriptedClient）を使うので、何度実行しても同じ結果になる。
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

from impact import REPORT_CHECKS, score_report  # noqa: E402
from measure import reset_data  # noqa: E402
from planner import (PlanError, SubGoal, parse_plan, topo_layers,  # noqa: E402
                     validate_plan)
from plans import (PLAN_CYCLE, PLAN_FRAGMENTED, PLAN_NOT_JSON, PLAN_OK,  # noqa: E402
                   TURNS_BUDGET, TURNS_EVERY, TURNS_FRAGMENTED, TURNS_NEWFACT,
                   TURNS_REPLAN, TURNS_STATIC_BROKEN, TURNS_STATIC_OK, plan_from)
from runner import run_noplan, run_planned, should_replan  # noqa: E402

TOOLS = ["book_room", "get_employee", "get_policy", "list_expenses", "read_file",
         "search_docs", "send_message", "submit_expense", "write_file"]


@pytest.fixture(scope="module", autouse=True)
def _fresh_data():
    """業務データを初期状態にしてから測る（前後で戻す）。"""
    reset_data()
    yield
    reset_data()


# --- 計画の構造 --------------------------------------------------------------
def test_依存が3つの層に分かれる():
    layers = [[sg.id for sg in layer] for layer in topo_layers(plan_from(PLAN_OK))]
    assert layers == [["sg_policy", "sg_expenses"],
                      ["sg_amount", "sg_deadline"],
                      ["sg_report"]]


def test_正しい計画には違反が無い():
    assert validate_plan(plan_from(PLAN_OK), TOOLS) == []


def test_必要な情報を作る依存が無いと実行前に分かる():
    violations = validate_plan(plan_from(PLAN_FRAGMENTED), TOOLS)
    assert len(violations) == 1
    assert "sg_amount_nocontext" in violations[0]
    assert "expenses" in violations[0]


def test_依存の循環を検出する():
    violations = validate_plan(plan_from(PLAN_CYCLE), TOOLS)
    assert any("循環" in v for v in violations)


def test_JSONでない計画はパースで落ちる():
    with pytest.raises(PlanError, match="JSON として読めません"):
        parse_plan(PLAN_NOT_JSON)


def test_違反のある計画は1手も実行しない():
    res = run_planned("検証あり", TURNS_FRAGMENTED, replan_policy="never")
    assert res.stop_reason == "invalid_plan"
    assert res.exec_steps == 0
    assert res.tool_calls == 0


# --- 方式ごとの振る舞い ------------------------------------------------------
def test_計画なしは最も安く抜けが多い():
    res = run_noplan()
    assert res.llm_calls == 4
    assert res.tool_names == ["search_docs", "list_expenses", "write_file"]
    score, missing = score_report(res.report)
    assert score == 3
    assert "現行規程の出典を示している" in missing


def test_静的計画は前提が正しければ満点で最も安い():
    res = run_planned("静的計画", TURNS_STATIC_OK, replan_policy="never")
    assert (res.plan_calls, res.exec_steps, res.llm_calls) == (1, 8, 9)
    assert score_report(res.report)[0] == len(REPORT_CHECKS)


def test_静的計画は失敗してもdoneで終わる():
    res = run_planned("静的計画", TURNS_STATIC_BROKEN, replan_policy="never")
    # 停止理由は done。失敗は成果物の欠けとしてだけ現れる（黙って壊れる）
    assert res.stop_reason == "done"
    assert res.failed_tool_calls == 1
    assert res.replans == []
    assert score_report(res.report) == (4, ["現行規程の出典を示している"])


def test_逐次再計画は失敗をきっかけに1回だけ作り直す():
    res = run_planned("逐次再計画", TURNS_REPLAN, replan_policy="on_trigger")
    assert len(res.replans) == 1
    assert res.replans[0].startswith("tool_failure")
    assert "指定できる項目" in res.replans[0]
    assert (res.plan_calls, res.exec_steps, res.llm_calls) == (2, 10, 12)
    assert score_report(res.report)[0] == len(REPORT_CHECKS)


def test_完了したサブゴールを二度実行しない():
    res = run_planned("逐次再計画", TURNS_REPLAN, replan_policy="on_trigger")
    # get_policy は失敗した1回と修正後の1回。list_expenses は1回だけ
    assert res.tool_names == ["get_policy", "get_policy", "list_expenses", "write_file"]


def test_予算トリガで縮小した計画に切り替える():
    res = run_planned("逐次再計画＋予算", TURNS_BUDGET, replan_policy="on_trigger",
                      budget_calls=12)
    assert res.llm_calls <= 12
    assert [r.split(":")[0] for r in res.replans] == ["tool_failure", "budget"]
    assert res.report_path == "impact_budget.md"
    assert "未調査" in res.report          # 落とした観点を黙って隠さない
    assert score_report(res.report)[0] == 4


def test_毎サブゴール再計画は成果が同じでコストだけ増える():
    every = run_planned("毎サブゴール再計画", TURNS_EVERY,
                        replan_policy="every_subgoal", max_replans=10)
    trigger = run_planned("逐次再計画", TURNS_REPLAN, replan_policy="on_trigger")
    assert every.plan_calls == 6 and trigger.plan_calls == 2
    assert every.exec_steps == trigger.exec_steps
    assert every.report == trigger.report


def test_新情報トリガでサブゴールを1つ足す():
    res = run_planned("新情報", TURNS_NEWFACT, replan_policy="on_trigger",
                      watch_facts=("rejected",))
    assert len(res.replans) == 1
    assert res.replans[0].startswith("new_fact")
    assert (res.plan_calls, res.exec_steps, res.llm_calls) == (2, 9, 11)
    # 完了済みのサブゴールを二度実行していない
    assert res.tool_names == ["get_policy", "list_expenses", "write_file"]
    assert score_report(res.report)[0] == len(REPORT_CHECKS)


def test_watch_factsを指定しなければ新情報トリガは立たない():
    res = run_planned("静的計画", TURNS_STATIC_OK, replan_policy="on_trigger")
    assert res.replans == []
    assert res.plan_calls == 1


def test_分解しすぎると観点が落ちる():
    res = run_planned("分解しすぎ", TURNS_FRAGMENTED, replan_policy="never",
                      enforce_validation=False)
    assert res.stop_reason == "done"
    assert score_report(res.report) == (4, ["金額基準の影響を特定している"])


# --- 再計画のトリガ ----------------------------------------------------------
REST = [SubGoal(id="sg_rest", goal="残りの仕事", max_steps=2)]


def _traj(ok: bool, content: str):
    from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: PLC0415

    traj = Trajectory(task_id="TASK-005-t", task="t")
    result = ToolResult("c0", True, content) if ok else ToolResult("c0", False, "", content)
    traj.steps.append(Step(index=0, thought="", calls=[ToolCall("c0", "list_expenses", {})],
                           results=[result], usage={}))
    return traj


@pytest.mark.parametrize(("traj", "kwargs", "expected"), [
    (_traj(False, "'経費精算規程' の規程は見つかりません。"), {}, "tool_failure"),
    (_traj(True, "EXP-0005 | 渡辺 陽 | 4400 | 交通費 | rejected"),
     {"plan_text": "申請一覧を取得する", "watch_facts": ("rejected",)}, "new_fact"),
    (_traj(True, "ok"), {"budget_calls": 6}, "budget"),
])
def test_3つのトリガがそれぞれ立つ(traj, kwargs, expected):
    reason = should_replan(traj, pending=REST, used_calls=5, **kwargs)
    assert reason is not None
    assert reason.startswith(expected)


def test_何も起きていなければ作り直さない():
    reason = should_replan(_traj(True, "ok"), pending=REST, used_calls=3, budget_calls=20)
    assert reason is None


def test_監視する語を宣言しなければ新情報トリガは立たない():
    # 「何でも新情報」にすると毎回作り直しになる。監視は明示的に宣言する
    reason = should_replan(_traj(True, "rejected"), pending=REST, used_calls=3)
    assert reason is None


# --- 決定性 ------------------------------------------------------------------
def test_2回走らせて軌跡と成果物が一致する():
    a = run_planned("逐次再計画", TURNS_REPLAN, replan_policy="on_trigger")
    b = run_planned("逐次再計画", TURNS_REPLAN, replan_policy="on_trigger")
    assert a.tool_names == b.tool_names
    assert a.report == b.report
    assert a.total_tokens == b.total_tokens
    assert a.replans == b.replans
