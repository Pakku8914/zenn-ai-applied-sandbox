"""復習04の軌跡テスト（pytest 版）。

    docker compose exec app python -m pytest src/review04 -q

固定データと決定的なオラクルを使うので、何度実行しても同じ結果になる。ここで固定して
いるのは「運用の意思決定」——同じ数字を見たら誰でも同じ一手にたどり着くこと——である。
解答を書くファイル（`answers.py`）には依存しないので、答えを消しても pytest は通る。

`release` と `improve` と `stopping` は業務データと作業領域を変える。各測定の前後で
`tools/make_data.py` と `clear_workspace()` を呼んで初期状態に戻す。
"""

from __future__ import annotations

from _paths import reset_data, setup

ROOT = setup()

import pytest  # noqa: E402

import budget  # noqa: E402
import capacity  # noqa: E402
import improve  # noqa: E402
import nextstep  # noqa: E402
import release  # noqa: E402
import signals  # noqa: E402
import stopping  # noqa: E402

from jobspec import clear_workspace  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _fresh_data():
    """測定の前後で業務データと作業領域を初期状態に戻す。"""
    reset_data()
    clear_workspace()
    yield
    reset_data()
    clear_workspace()


@pytest.fixture(scope="module")
def swap_rows() -> list[dict]:
    return release.swap_table()


@pytest.fixture(scope="module")
def canary_rows() -> list[dict]:
    return release.canary_table()


@pytest.fixture(scope="module")
def traces() -> list:
    return improve.traces()


@pytest.fixture(scope="module")
def cap_rows() -> list[dict]:
    return capacity.table()


# --- 支払う（S16 の形 × 本章の仮の単価表）------------------------------------
def test_月次の費用と超過が決定的に出る():
    total = signals.monthly_rin()
    assert total == 29_494_800
    assert total - signals.BUDGET_RIN == 4_494_800


def test_件数のシェアと費用のシェアは一致しない():
    loop = signals.find_row("同じ検索を繰り返す")
    total = signals.monthly_rin()
    assert round(loop[1] / 1000 * 100, 1) == 4.0
    assert round(loop[1] * signals.row_rin(loop) / total * 100, 1) == 12.3


def test_予算に収める打ち手は削減額の大きい順に選ばない():
    plan = budget.plan(25_000_000)
    assert plan["picked"] == ["P1"]
    assert plan["after"] == 24_545_700
    assert budget.savings(budget.by_code("P2")) > budget.savings(budget.by_code("P1"))


def test_前提を差し替えると打ち手の順位が入れ替わる():
    assert [r["code"] for r in budget.ranked_under(signals.PRICES)] \
        == ["A1", "A3", "A2", "A4"]
    assert [r["code"] for r in budget.ranked_under(signals.PRICES_OUT_HEAVY)] \
        == ["A4", "A1", "A2", "A3"]
    assert budget.robust_pick() == "A1"


# --- 測る × 支払う（S13 × S15）-----------------------------------------------
def test_受け入れ基準の数字ひとつで差し替えの判断が変わる(swap_rows):
    assert [r["厳しい基準"][0] for r in swap_rows] \
        == ["出す", "出さない", "出さない", "出さない"]
    assert [r["緩い基準"][0] for r in swap_rows] \
        == ["出す", "様子を見る", "出さない", "出さない"]


def test_安全に関わる判断は基準を緩めても変わらない(swap_rows):
    forbidden_row, thin_row = swap_rows[2], swap_rows[3]
    assert forbidden_row["厳しい基準"][0] == forbidden_row["緩い基準"][0] == "出さない"
    assert thin_row["厳しい基準"][0] == thin_row["緩い基準"][0] == "出さない"
    assert thin_row["same_tools"] and thin_row["missing"] == ["規程違反", "EXP-0002"]


# --- 追う（S14）--------------------------------------------------------------
def test_頻度の1位と今週直す1件は一致しない(traces):
    freq = improve.frequency_rows(traces)
    scored = improve.ranked(freq)
    assert freq[0]["symptom"] == "同じ操作の反復"
    assert improve.pick_one(scored) == "外部宛の送信"


def test_被害の重みを掛けるとスコアの並びが変わる(traces):
    scored = improve.ranked(improve.frequency_rows(traces))
    assert [r["スコア"] for r in scored] == [5, 3, 2, 2, 2, 0]


def test_取りこぼし0の案のうち保存量が最小のものを選ぶ(traces):
    choice = improve.sampling_choice(traces)
    assert choice["lost"] == 0
    assert choice["kept"] == "7/8"


# --- 回す（S15）--------------------------------------------------------------
def test_完了の下限を決めるのは多重度ではなくレート上限(cap_rows):
    assert {r["workers"]: r["makespan"] for r in cap_rows} == {1: 24, 2: 12, 4: 13, 8: 12}
    assert capacity.floor() == 12
    assert capacity.decide(10, cap_rows)["多重度"] is None
    assert capacity.decide(10, cap_rows)["必要なレート上限"] == 3


def test_下限に届いたあと多重度を上げると待ちだけが増える(cap_rows):
    assert capacity.decide(15, cap_rows)["多重度"] == 2
    slow = capacity.slowdown()
    assert slow["makespan"] == (12, 13)
    assert slow["waits"] == (0, 19)


def test_カナリアは判定より前に前提を見る(canary_rows):
    head5 = canary_rows[0]
    assert head5["verdict"] == "進む"
    assert head5["missing"] == ["send"]
    assert head5["採用"] == "判定を採用しない"


def test_型ごとに選べば同じ5パーセントで欠陥に当たる(canary_rows):
    strat5 = canary_rows[2]
    assert (strat5["段階"], strat5["件数"], strat5["禁止"]) == ("5%", 5, 1)
    assert strat5["採用"] == "止める"


# --- 4系統をまとめて1つの判断にする -------------------------------------------
def test_次の一手はいつも1つだけ返る():
    assert {s.week: nextstep.decide(s)["次の一手"] for s in nextstep.WEEKS} == {
        "W1": "止めて戻す", "W2": "原因を1件に絞る", "W3": "内容検査を足す",
        "W4": "容量を決め直す", "W5": "コストの打ち手を選ぶ", "W6": "何もしない"}
    assert nextstep.also_triggered(nextstep.WEEKS[0]) == ["コストの打ち手を選ぶ"]


def test_停止理由と状態と結果は別の軸():
    rows = stopping.case_rows()
    assert [r["結果"] for r in rows] == ["report", "partial", "insufficient",
                                         "partial", "handoff", "handoff"]


def test_打ち切りは引き継ぎ書が出ても結果は材料不足():
    live = stopping.live_rows()
    assert [(r["job_id"], r["結果"]) for r in live] == [
        ("TASK-153", "report"), ("TASK-172", "insufficient"), ("TASK-157", "handoff")]
    assert live[1]["引き継ぎ書"] == "あり（人に引き継ぎます）"
