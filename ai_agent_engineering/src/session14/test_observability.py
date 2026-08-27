#!/usr/bin/env python3
"""セッション14の軌跡テスト。

    python -m pytest src/session14 -q

トレースの検査は「人が出力を読む」形にしない。**スパンの数・相関ID・再生結果**を
機械が判定できる形にしておくと、章を書き換えたときに壊れたことに気づける。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, str(_p))

from breakdown import kind_totals, step_rows, token_shape  # noqa: E402
from failtags import root_step, symptoms, verdict  # noqa: E402
from redaction import FULL, FULL_MASKED, record_for, run_leak, secret_hits, cleanup  # noqa: E402
from replay import (exception_name, make_cassette, replay_with_fixture,  # noqa: E402
                    replay_with_recorded_ids, same_trajectory, save_cassette)
from spanlog import (UNITS_A, UNITS_B, ancestors, counts_by_kind,  # noqa: E402
                     find_by_call_id, reset_data, run_case, spans_from_trajectory)

from agentkit.biztools import build_registry  # noqa: E402


@pytest.fixture(autouse=True)
def clean_data():
    reset_data()
    yield
    cleanup()
    reset_data()


def test_span_tree_shape():
    spans = spans_from_trajectory(run_case("expense_report", "経費レポート作成"))
    assert counts_by_kind(spans) == {"task": 1, "step": 4, "llm": 4, "tool": 3}
    assert spans[0].parent_id is None
    assert spans[0].ms == 2060


def test_call_id_is_unique_and_traceable():
    spans = spans_from_trajectory(run_case("expense_report", "経費レポート作成"))
    hits = find_by_call_id(spans, "expense_report-3-0")
    assert len(hits) == 1
    assert hits[0].name == "write_file"
    assert ancestors(spans, hits[0].span_id)[-1] == "TASK-expense_report/00"


def test_breakdown_depends_on_units():
    traj = run_case("expense_report", "経費レポート作成")
    assert [r["ms"] for r in step_rows(traj, UNITS_A)] == [520, 520, 520, 500]
    assert kind_totals(traj, UNITS_A)["top"] == "llm"
    assert kind_totals(traj, UNITS_B)["top"] == "tool"


def test_input_tokens_grow_every_step():
    shape = token_shape(run_case("expense_report", "経費レポート作成"))
    assert shape["monotonic"] is True
    assert shape["peak"] == shape["steps"] - 1


def test_full_grain_carries_secrets():
    spans = spans_from_trajectory(run_leak())
    assert secret_hits([record_for(s, FULL) for s in spans]) == 2
    assert secret_hits([record_for(s, FULL_MASKED) for s in spans]) == 0


def test_replay_reproduces_the_same_failure():
    task, max_steps = "同じ検索を繰り返す", 6
    original = run_case("max_steps_loop", task, max_steps)
    cassette = make_cassette(task, original, build_registry().specs())
    save_cassette("s14_max_steps_loop", cassette)

    fixture = replay_with_fixture(task, "s14_max_steps_loop", max_steps=max_steps)
    assert (len(fixture.steps), fixture.stop_reason) == (1, "error")
    assert exception_name(fixture) == "KeyError"

    replayed = replay_with_recorded_ids(task, cassette, max_steps=max_steps)
    assert all(same_trajectory(original, replayed).values())


def test_symptoms_and_root_step():
    loop = run_case("max_steps_loop", "同じ検索を繰り返す", 6)
    assert symptoms(loop) == ["打ち切り", "同じ操作の反復"]
    assert root_step(loop) == "step[2]"
    assert verdict(loop) == "失敗"

    ok = run_case("expense_report", "経費レポート作成")
    assert symptoms(ok) == []
    assert verdict(ok) == "正常"
