"""復習02の軌跡テスト（pytest 版）。

    docker compose exec app python -m pytest src/review02 -q

決定的なオラクル（ScriptedClient）と固定データを使うので、何度実行しても同じ結果に
なる。ここで固定しているのは「構造の選び方によって、再開可能性・権限・副作用が
どう変わるか」である。解答を書くファイル（answers.py）には依存しないので、
答えを消しても pytest は通る。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

import pytest  # noqa: E402

from agentkit.biztools import build_registry  # noqa: E402

import memo  # noqa: E402
import resume as resume_mod  # noqa: E402
import split  # noqa: E402
import workload  # noqa: E402
from assign import (BAD_ASSIGNMENT, BROKEN_PLAN, GOOD_ASSIGNMENT,  # noqa: E402
                    TEAM_PLAN, check_assignment, handoff_count)
from planner import validate_plan  # noqa: E402 (S05)


@pytest.fixture(scope="module")
def registry():
    return build_registry()


@pytest.fixture(scope="module")
def resume_rows():
    return resume_mod.variants()


@pytest.fixture(scope="module")
def split_rows():
    return split.compare()


def test_ツール結果がコンテキストを支配する():
    assert memo.dominance() == {"合計": 1216, "ツール結果": 1096, "割合(%)": 90,
                                "項目数": 6, "ツール結果の項目数": 4}


@pytest.mark.parametrize(
    ("index", "tokens", "constraints", "facts"),
    [(0, 1216, "3/3", "2/2"), (1, 320, "0/3", "0/2"), (2, 280, "3/3", "0/2"),
     (3, 420, "3/3", "0/2"), (4, 320, "3/3", "2/2")])
def test_圧縮方式ごとに残るものが違う(index, tokens, constraints, facts):
    row = memo.compare()[index]
    assert (row["近似トークン"], row["制約"], row["事実"]) == (tokens, constraints, facts)


def test_状態へ移せば履歴を削っても判断材料が残る():
    state_memory, state = memo.state_first()
    truncated, _ = memo.truncate()
    assert state_memory.total_tokens() == truncated.total_tokens()
    assert memo.kept(state_memory, state, memo.FACTS) == 2
    assert memo.kept(truncated, {}, memo.FACTS) == 0


def test_状態を捨てると再開できない(resume_rows):
    assert resume_rows[0]["再開できる"] is False
    assert resume_rows[0]["予約の行数"] == 0


def test_軌跡を圧縮しても同じ結論に着く(resume_rows):
    compressed, full = resume_rows[1], resume_rows[2]
    assert compressed["違反"] == full["違反"] == 2
    assert (compressed["到達した手数"], full["到達した手数"]) == (6, 9)
    assert compressed["予約の行数"] == full["予約の行数"] == 1


def test_本文を捨てると判断のやり直しができない(resume_rows):
    assert resume_rows[3]["再開できる"] is True
    assert resume_rows[3]["基準を変えて再計算できる"] is False


def test_分けると手数は増え権限と履歴は縮む(split_rows):
    solo, orchestrated = split_rows[0], split_rows[1]
    assert (solo["手数"], orchestrated["手数"]) == (5, 6)
    assert (solo["1体のツール最大"], orchestrated["1体のツール最大"]) == (5, 3)
    assert (solo["最長の履歴"], orchestrated["最長の履歴"]) == (5, 3)


def test_自由文で引き継ぐと成果が落ちる(split_rows):
    orchestrated, handed_off = split_rows[1], split_rows[2]
    assert (orchestrated["予約の行数"], handed_off["予約の行数"]) == (1, 0)
    assert handed_off["手数"] > orchestrated["手数"]
    assert orchestrated["レポート"] is handed_off["レポート"] is True


def test_引き継ぎは構造化すれば落ちない():
    loss = split.handoff_loss()
    assert loss["自由文"] == ["EXP-0004"]
    assert loss["構造化"] == list(split.NEEDED)


def test_割り当ては配る前に検査できる(registry):
    assert check_assignment(TEAM_PLAN, GOOD_ASSIGNMENT, registry) == []
    assert len(check_assignment(TEAM_PLAN, BAD_ASSIGNMENT, registry)) == 2
    assert handoff_count(TEAM_PLAN, GOOD_ASSIGNMENT) == 1
    assert handoff_count(TEAM_PLAN, BAD_ASSIGNMENT) == 2


def test_計画そのものも実行前に止まる(registry):
    assert validate_plan(TEAM_PLAN, registry.names()) == []
    assert len(validate_plan(BROKEN_PLAN, registry.names())) == 2


@pytest.mark.parametrize(
    ("name", "state", "team"),
    [("請求書1件の区分を判定する", "履歴のみ", "単体"),
     ("四半期の棚卸し（洗い出し→レポート→報告会の予約）", "状態機械", "単体"),
     ("全部門の四半期監査（4部門ぶんの部門別レポート）", "構造体＋履歴", "オーケストレータ"),
     ("手順書を最新の規程から書き直す", "履歴のみ", "ハンドオフ")])
def test_構造の選択が規則で決まる(name, state, team):
    decided = workload.decide(workload.by_name(name))
    assert decided["状態の持ち方"] == state
    assert decided["体制"] == team
