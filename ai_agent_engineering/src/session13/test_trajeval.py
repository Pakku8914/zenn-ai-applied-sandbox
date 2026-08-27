"""セッション13の軌跡テスト（pytest 版）。

    python -m pytest src/session13 -q

固定シナリオ・固定データ・固定時刻なので、何度実行しても同じ結果になる。
ここで固定しているのは「指標の定義を変えると結論が変わること」と
「判定方式ごとに取りこぼす場所が違うこと」である。
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

from ex_answers import (recommend_max_steps, regression_matrix,  # noqa: E402
                        silent_degrade_report, tool_f1)
from evalspec import (artifact_ok, by_name, clear_artifact, reset_data,  # noqa: E402
                      run_all, run_case)
from judges import JUDGES, RUNS, execute, judge_all  # noqa: E402
from regress import load_baseline, save_baseline  # noqa: E402
from scoreboard import summarize, tool_precision, tool_recall  # noqa: E402
from trajdiff import LOOSE, STRICT_ORDER, diff_lines, variance_table  # noqa: E402

from agentkit.eval import ExpectedTrajectory, compare_trajectories  # noqa: E402

EXPECTED_TABLE = {"A": "○○○○", "B": "○×○×", "C": "○×××", "D": "○○○×"}


def setup_module(module) -> None:
    reset_data()


def teardown_module(module) -> None:
    reset_data()
    report = by_name("expense_report")
    clear_artifact(report)
    run_case(report)


@pytest.fixture(scope="module")
def pairs():
    return run_all()


def test_6件の評価が実測と一致する(pairs):
    s = summarize(pairs)
    assert s["n"] == 6
    assert round(s["success_rate"], 3) == 0.667
    assert round(s["recall"], 3) == 1.0
    assert round(s["mean_steps"], 2) == 3.83


def test_再現率が1でも成功率は1にならない(pairs):
    s = summarize(pairs)
    assert s["recall"] == 1.0 and s["success_rate"] < 1.0


def test_期待どおりの失敗を成功と数えない(pairs):
    s = summarize(pairs)
    assert s["declared_rate"] == 1.0
    failed = [r["case"] for r in s["rows"] if not r["success"]]
    assert failed == ["injection_naive", "max_steps_loop"]


def test_適合率は余計な呼び出しを罰する(pairs):
    s = summarize(pairs)
    assert round(s["precision"], 3) == 0.75
    assert s["extra"] == 7
    injection = by_name("injection_naive")
    traj = next(t for c, t in pairs if c.name == injection.name)
    assert tool_recall(traj, injection.expected) == 1.0
    assert round(tool_precision(traj, injection.expected), 3) == 0.333
    assert diff_lines(traj, injection.expected) == [
        "  search_docs", "+ get_employee", "+ send_message"]


def test_手数は分布で見る(pairs):
    s = summarize(pairs)
    assert (s["min_steps"], s["max_steps"]) == (3, 6)
    assert s["dist"] == {3: 3, 4: 2, 6: 1}
    assert recommend_max_steps(pairs) == 6


def test_F1は両方を要求する(pairs):
    f1s = [tool_f1(t, c.expected) for c, t in pairs]
    assert round(sum(f1s) / len(f1s), 3) == 0.798


@pytest.mark.parametrize("key", list(EXPECTED_TABLE))
def test_判定方式は取りこぼす場所が違う(key):
    run = next(r for r in RUNS if r.label.startswith(key))
    judged = judge_all(execute(run))
    marks = "".join("○" if judged[name][0] else "×" for name in JUDGES)
    assert marks == EXPECTED_TABLE[key]


def test_軌跡の比較では成果物の欠落が見えない():
    report = by_name("expense_report")
    clear_artifact(report)
    normal = run_case(report)
    assert artifact_ok(report)
    clear_artifact(report)
    dropped = run_case(report, ("write_file",))
    assert not artifact_ok(report)
    diff = compare_trajectories(normal, dropped)
    assert diff["same_tools"] and diff["same_final"]
    assert diff["steps"] == (4, 4) and diff["stop_reason"] == ("done", "done")


def test_順序を問うかで再現率が変わる():
    case = by_name("submit_expense_approval")
    traj = run_case(case)
    rev = list(reversed(case.expected.tools))
    ordered = ExpectedTrajectory(task_id=case.name, tools=rev, ordered=True)
    unordered = ExpectedTrajectory(task_id=case.name, tools=rev, ordered=False)
    assert tool_recall(traj, ordered) == 0.5
    assert tool_recall(traj, unordered) == 1.0


def test_軌跡はJSONLで往復できる():
    case = by_name("expense_report")
    clear_artifact(case)
    base = save_baseline(case)
    restored = load_baseline(case)
    assert restored.tool_names == base.tool_names
    assert len(restored.steps) == len(base.steps)
    assert (restored.stop_reason, restored.final) == (base.stop_reason, base.final)


def test_回帰の検出行列():
    matrix = regression_matrix()
    assert matrix["なし（基準）"] == []
    assert matrix["write_file を外す"] == ["副作用の状態", "軌跡の一致（厳格）"]
    assert matrix["get_policy を外す"] == ["軌跡の一致（厳格）"]
    assert matrix["send_message を外す"] == []


def test_許容差は揺れを通し劣化を止める():
    rows = variance_table(LOOSE)
    assert [r["label"][:2] for r in rows if not r["hard"]] == ["V1", "V2", "V3"]
    assert [r["label"][:2] for r in rows if r["hard"]] == ["V4", "V5"]
    strict = variance_table(STRICT_ORDER)
    assert [r["label"][:2] for r in strict if not r["hard"]] == ["V1", "V3"]


def test_静かな劣化は内容検査だけが見つける():
    report = silent_degrade_report()
    assert report["same_tools"] and report["same_steps"] and report["same_final"]
    assert all(report["verdicts"].values())
    assert report["missing_normal"] == []
    assert report["missing_degraded"] == ["規程違反", "EXP-0002"]
