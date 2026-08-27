"""セッション15の軌跡テスト（pytest 版）。

    python -m pytest src/session15 -q

固定シナリオ・固定データ・仮想時計なので、何度実行しても同じ結果になる。
ここで固定しているのは「並行実行の設計判断が数字として再現すること」である。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from jobspec import clear_workspace, reset_data, total_steps, workload  # noqa: E402
from opsconfig import OpsConfig  # noqa: E402
from queue_sim import (floor_seconds, multiplicity_rows, progress_at,  # noqa: E402
                       run_crash, run_isolation, run_workload, strategy_rows)
from ratelimit import backoff_ticks, serve_demo  # noqa: E402
from rollout import canary_ids, check_runbook, kind_of, render_runbook  # noqa: E402
from swap import accept_swap, swap_rows  # noqa: E402


def setup_module(module) -> None:
    reset_data()
    clear_workspace()


def teardown_module(module) -> None:
    reset_data()
    clear_workspace()


def test_多重度を上げても下限より速くならない() -> None:
    rows = multiplicity_rows()
    floor = floor_seconds(total_steps(workload()), 2)
    assert floor == 12
    assert [r["makespan"] for r in rows] == [24, 12, 13, 12]
    assert min(r["makespan"] for r in rows) == floor


def test_仕事の量は多重度で変わらない() -> None:
    assert {r["llm_calls"] for r in multiplicity_rows()} == {24}


def test_処理順は決定的である() -> None:
    assert run_workload(workers=4).trace() == run_workload(workers=4).trace()


def test_順番待ちは無駄な呼び出しを出さない() -> None:
    rows = {r["label"]: r for r in strategy_rows()}
    assert rows["当たってから謝る（バックオフ）"]["wasted"] == 6
    assert rows["手前で順番待ち（行列）"]["wasted"] == 0
    # 待機の合計は順番待ちの方が長いのに、完了は速い
    assert rows["手前で順番待ち（行列）"]["waited"] > rows["当たってから謝る（バックオフ）"]["waited"]
    assert rows["手前で順番待ち（行列）"]["makespan"] < rows["当たってから謝る（バックオフ）"]["makespan"]


def test_バックオフはティックに切り上げても指数で伸びる() -> None:
    assert [backoff_ticks(i) for i in range(6)] == [1, 1, 2, 4, 8, 8]


def test_不公平な行列は後ろのワーカーを飢えさせる() -> None:
    assert serve_demo(fair=True) == [3, 3, 3, 3]
    assert serve_demo(fair=False) == [6, 6, 0, 0]
    fair = run_workload(workers=4, fair=True)
    unfair = run_workload(workers=4, fair=False)
    assert fair.max_wait_to_first_step() == 1
    assert unfair.max_wait_to_first_step() == 9


def test_キャンセルは完了扱いにしない() -> None:
    cut = run_workload(workers=2, cancel={"TASK-157": 9})
    stopped = cut.by_id("TASK-157")
    assert cut.llm_calls == 21 and cut.states() == "done 7 / cancelled 1"
    assert stopped.trajectory.stop_reason == "error"
    assert "利用者がキャンセルしました" in (stopped.trajectory.final or "")


def test_進捗は割合ではなく現在地で見せる() -> None:
    view = progress_at(run_workload(workers=2), "TASK-153", 4)
    assert view["steps_done"] == 3 and view["last_action"] == "write_file"
    assert "percent" not in view


def test_暴走した1件だけが打ち切られる() -> None:
    iso = run_isolation()
    assert iso.states() == "done 2 / limited 1"
    assert iso.by_id("TASK-172").trajectory.stop_reason == "max_steps"


def test_再開すれば副作用を二度実行しない() -> None:
    assert run_crash(True).tool_counts["write_file"] == 1
    assert run_crash(False).tool_counts["write_file"] == 2


def test_軌跡の差分は引数を見ない() -> None:
    rows = {r["label"]: r for r in swap_rows()}
    thin = rows["D 中身が薄くなる"]
    assert thin["same_tools"] and thin["same_final"] and thin["steps"] == (4, 4)
    assert thin["missing"] == ["規程違反", "EXP-0002"]
    assert accept_swap(thin) == "出さない"


def test_カナリアは割合ではなく型で決まる() -> None:
    head = canary_ids(5, "head")
    strat = canary_ids(5, "stratified")
    assert len(head) == len(strat) == 5
    assert "send" not in {kind_of(t) for t in head}
    assert "send" in {kind_of(t) for t in strat}


def test_振り分けは安定していて単調に広がる() -> None:
    for method in ("serial", "hash"):
        assert set(canary_ids(5, "head", method)) <= set(canary_ids(25, "head", method))


def test_設定は起動時に検証される() -> None:
    import pytest  # noqa: PLC0415

    cfg = OpsConfig.load()
    assert cfg.workers == 2 and cfg.rate_limit_per_second == 2
    for change in ({"workers": 0}, {"rate_mode": "yolo"}, {"canary_percents": (25, 5)}):
        with pytest.raises(ValueError):
            cfg.with_(**change)


def test_runbookの節がそろっている() -> None:
    ok, missing = check_runbook(render_runbook())
    assert ok, missing
