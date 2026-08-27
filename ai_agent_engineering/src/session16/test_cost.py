#!/usr/bin/env python3
"""セッション16の軌跡テスト。

    python -m pytest src/session16 -q

コストの設計は「安くなったか」だけでは判定できない。安くしたせいで軌跡が変わって
いないか（成功率が落ちていないか）を同じテストで見る。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _d in (ROOT, HERE, ROOT / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from agentkit.eval import task_success, tool_choice_accuracy  # noqa: E402
from capguard import (CostGuard, admit_rows, behaviour_rows,  # noqa: E402
                      check_handoff, input_budget)
from costshape import (cacheable_tokens, detail_trajectory, reset_data,  # noqa: E402
                       run_one, unstable_head)
from prices import HIGH, traj_cost  # noqa: E402
from resultsize import pad_rows  # noqa: E402
from tiering import (EXPECTED, degraded_trajectory, precision,  # noqa: E402
                     route_all_high, route_by_role, tiered_cost)


@pytest.fixture(autouse=True)
def clean_data():
    """各テストの前後で業務データを初期状態に戻す（S14 と同じ作法）。"""
    reset_data()
    yield
    reset_data()


def test_input_tokens_grow_every_step():
    """履歴が毎回全部送られるので、入力はステップごとに必ず増える。"""
    traj = detail_trajectory()
    ins = [s.usage["input_tokens"] for s in traj.steps]
    assert ins == [13, 129, 374, 545]
    assert all(a < b for a, b in zip(ins, ins[1:]))


def test_tool_result_is_billed_for_remaining_steps():
    """ツール結果 300 文字は「残りステップ数 × 100 トークン」ぶん課金される。"""
    rows = pad_rows()
    assert [r["増分"] for r in rows[1:]] == [300, 200, 100]
    assert [r["増分"] for r in rows[1:]] == [r["理論値"] for r in rows[1:]]


def test_prefix_cache_breaks_when_the_head_changes():
    """先頭に毎回変わる文字列を入れると、前方一致の再利用が全部消える。"""
    traj = detail_trajectory()
    assert cacheable_tokens(traj) == 516
    assert cacheable_tokens(traj, unstable_head) == 0


def test_tiering_does_not_change_the_trajectory():
    """階層化は課金の話。軌跡と成果物は1文字も変わってはいけない。"""
    traj = detail_trajectory()
    assert tiered_cost(traj, route_all_high) == 13010
    assert tiered_cost(traj, route_by_role) == 6665
    assert task_success(traj, EXPECTED)
    assert tool_choice_accuracy(traj, EXPECTED) == 1.0


def test_degraded_model_fails_the_trajectory_test():
    """安くなっても、余計なツールを呼ぶようになったら不合格にする。"""
    detail_trajectory()
    bad = degraded_trajectory()
    assert len(bad.steps) == 5
    assert not task_success(bad, EXPECTED)
    assert tool_choice_accuracy(bad, EXPECTED) == 1.0   # 再現率だけでは気づけない
    assert precision(bad) == 0.75                        # 適合率で気づく


def test_guard_respects_the_limit_where_budget_does_not():
    """事後判定は上限 520 を 1,061 まで超える。見積もり判定なら 516 で止まる。"""
    detail_trajectory()
    after = run_one("expense_report", "経費レポート作成",
                    task_id="TASK-budget", budget=input_budget(520))
    guard = run_one("expense_report", "経費レポート作成",
                    task_id="TASK-guard", budget=CostGuard(520))
    assert after.total_tokens["input"] == 1061 and after.stop_reason == "done"
    assert guard.total_tokens["input"] == 516 and guard.stop_reason == "budget"
    assert guard.total_tokens["input"] <= 520


def test_downgrade_completes_within_the_cap():
    """上限 10,000 cu で完走できるのは格下げだけ。打ち切りは成果を残さない。"""
    rows = {r["振る舞い"]: r for r in behaviour_rows(10_000)}
    stop = rows["打ち切り（fail）"]
    down = rows["格下げ（downgrade）"]
    assert (stop["手数"], stop["cu"], stop["停止理由"]) == (3, 5960, "budget")
    assert (down["手数"], down["cu"], down["停止理由"]) == (4, 6665, "done")
    assert down["cu"] <= 10_000
    assert check_handoff(rows["人間に渡す（handoff）"]["note"]) == []


def test_per_task_limit_protects_the_daily_limit():
    """1タスク上限が無いと、暴走した1件が正常なタスクを締め出す。"""
    costs = [("経費レポート作成", 12620), ("会議室予約（競合あり）", 6110),
             ("経費申請（5万円以上）", 6190), ("同じ検索を繰り返す", 30260)]
    plain = admit_rows(costs, 50_000)
    capped = admit_rows(list(reversed(costs)), 50_000, 15_000)
    assert [r["タスク"] for r in plain if r["判定"] == "拒否"] == ["同じ検索を繰り返す"]
    assert all(r["判定"] != "拒否" for r in capped)
    assert capped[-1]["累計"] == 39920


def test_cost_is_not_proportional_to_steps():
    """手数 1.5 倍のタスクでコストは 2.40 倍。比例しない。"""
    from costshape import table_rows  # noqa: PLC0415

    rows = table_rows()
    normal, runaway = rows[0], rows[3]
    assert traj_cost_like(normal) == 12620 and traj_cost_like(runaway) == 30260
    assert round(runaway["cu"] / normal["cu"], 2) == 2.40
    assert runaway["手数"] / normal["手数"] == 1.5


def traj_cost_like(row: dict) -> int:
    """表の1行から単価を計算し直す（表の値と一致することを確かめる）。"""
    return HIGH.cost(row["in"], row["out"])


def test_traj_cost_matches_the_table():
    """`traj_cost` と、表に載せた値が一致する。"""
    traj = detail_trajectory()
    assert traj_cost(traj, HIGH) == 13010
