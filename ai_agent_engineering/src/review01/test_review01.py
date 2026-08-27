"""復習01の軌跡テスト（pytest 版）。

    docker compose exec app python -m pytest src/review01 -q

決定的なオラクル（ScriptedClient）と固定データを使うので、何度実行しても同じ結果に
なる。ここで固定しているのは「同じ症状に見える軌跡が、違う原因に切り分けられること」。
解答を書くファイル（answers.py）には依存しないので、答えを消しても pytest は通る。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

import pytest  # noqa: E402

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: E402

import traces  # noqa: E402
import triage  # noqa: E402
from batch import plan_batches  # noqa: E402
from diagnose import diagnose, is_trustworthy_done  # noqa: E402
from plan import REVIEW_PLAN, Plan, SubGoal, should_replan  # noqa: E402
from report import diagnose_report  # noqa: E402
from sideeffects import run_pair  # noqa: E402
from tokens import history_tokens  # noqa: E402

CAUSES = {
    "A_normal": [],
    "B_stuck_loop": ["計画がない"],
    "C_rephrase_loop": ["道具のエラーが不親切", "道具の粒度が粗い"],
    "D_false_report": ["報告が実態と違う"],
    "E_under_limit": ["上限不足"],
    "F_actionable_loop": ["モデルが直せない"],
}


@pytest.fixture(scope="module")
def cases():
    return traces.by_label()


@pytest.mark.parametrize("label", list(CAUSES))
def test_症状から原因へ切り分けられる(cases, label):
    case = cases[label]
    assert diagnose(case.traj, registry=case.registry, allowed_tools=case.allowed,
                    needed_steps=case.needed_steps) == CAUSES[label]


def test_同じ停止理由でも原因が違う(cases):
    stuck, under = cases["B_stuck_loop"], cases["E_under_limit"]
    assert stuck.traj.stop_reason == under.traj.stop_reason == "max_steps"
    assert CAUSES["B_stuck_loop"] != CAUSES["E_under_limit"]


def test_done_を鵜呑みにしない(cases):
    def trust(label):
        case = cases[label]
        return is_trustworthy_done(case.traj, registry=case.registry,
                                   allowed_tools=case.allowed)

    assert trust("A_normal") is True
    assert trust("D_false_report") is False


def test_並列にしてよい塊だけがまとまる():
    registry = build_registry()

    def shape(*names):
        calls = [ToolCall(f"c{i}", name, {}) for i, name in enumerate(names)]
        return [(mode, [c.name for c in group])
                for mode, group in plan_batches(registry, calls)]

    assert shape("get_policy", "list_expenses", "search_docs") == [
        ("parallel", ["get_policy", "list_expenses", "search_docs"])]
    assert shape("get_policy", "list_expenses", "write_file") == [
        ("parallel", ["get_policy", "list_expenses"]), ("serial", ["write_file"])]
    assert shape("search_docs", "send_message") == [
        ("serial", ["search_docs"]), ("serial", ["send_message"])]


def test_結果の大きさが履歴に積み上がる():
    assert history_tokens([1038, 1038, 1038]) == [10, 356, 702, 1048]
    assert history_tokens([102, 102, 102]) == [10, 44, 78, 112]
    assert round(2116 / 244, 1) == 8.7


def test_計画の実行順は決定的():
    assert REVIEW_PLAN.order() == ["expenses", "policy", "check", "report"]
    with pytest.raises(ValueError):
        Plan("循環", [SubGoal("a", "get_policy", ("b",)),
                     SubGoal("b", "get_policy", ("a",))]).order()


def test_再計画のトリガが3つとも効く(cases):
    assert should_replan(cases["C_rephrase_loop"].traj, REVIEW_PLAN,
                         done=set(), max_steps=4)[0] is True
    broken = Trajectory(task_id="TASK-R01-X", task=REVIEW_PLAN.task)
    broken.steps.append(Step(0, "規程を読む",
                             [ToolCall("x0", "get_policy", {"topic": "接待費"})],
                             [ToolResult("x0", False, "", "見つかりません。")], {}))
    assert should_replan(broken, REVIEW_PLAN, done=set(), max_steps=8)[0] is True
    assert should_replan(cases["B_stuck_loop"].traj, REVIEW_PLAN,
                         done=set(), max_steps=6)[0] is True
    assert should_replan(cases["B_stuck_loop"].traj, REVIEW_PLAN,
                         done=set(), max_steps=20)[0] is False


def test_軌跡が同じでも副作用は同じではない():
    pair = run_pair()
    assert pair["検証なし"]["steps"] == pair["検証あり"]["steps"] == 3
    assert pair["検証なし"]["modes"] == pair["検証あり"]["modes"] == ["権限逸脱"]
    assert (pair["検証なし"]["added"], pair["検証あり"]["added"]) == (2, 1)
    assert pair["検証なし"]["categories"] == ["打ち上げ", "接待交際費"]
    assert pair["検証あり"]["categories"] == ["接待交際費"]


def test_3択と上限設計が繋がる():
    truth = triage.truth()
    assert truth["請求書の区分付け"]["choice"] == "ツール付き単発呼び出し"
    assert truth["月次の経費集計"]["choice"] == "ワークフロー"
    assert truth["監査指摘の洗い出し"]["max_steps"] == 7
    assert truth["取引先への謝罪文送付"]["on_limit"] == "handoff"


def test_診断レポートに5つの項目が並ぶ(cases):
    text = diagnose_report(cases["C_rephrase_loop"])
    assert "- 原因: 道具のエラーが不親切, 道具の粒度が粗い" in text
    assert len(text.splitlines()) == 6
