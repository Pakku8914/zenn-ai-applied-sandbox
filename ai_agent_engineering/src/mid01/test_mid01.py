"""調査エージェントの軌跡テスト（成果物④）。

    docker compose exec app python -m pytest src/mid01 -q

シナリオは9本ある。うち異常系は5本で、**上限到達・道具の失敗・情報不足**の3つを
必ず含む。`ScriptedClient` で応答を固定しているので、何度実行しても同じ軌跡になる。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _paths import setup  # noqa: E402

ROOT = setup()

import pytest  # noqa: E402

from analysis import extract_threshold, find_findings, read_artifact  # noqa: E402
from cases import by_name, reset_data, run_case  # noqa: E402
from machine import LOOP_LIMITS, TRANSITIONS  # noqa: E402
from research_plan import (PLAN_FORBIDDEN, PLAN_UNMAPPED, RESEARCH_PLAN,  # noqa: E402
                           SUBGOAL_STATES, check_plan)
from score import ungrounded_ids  # noqa: E402
from spec import build_registry  # noqa: E402

CASES = by_name()


@pytest.fixture(scope="module", autouse=True)
def _fresh_data():
    """業務データを初期状態にしてから測る（前後で戻す）。"""
    reset_data()
    yield
    reset_data()


def run(name: str) -> dict:
    return run_case(CASES[name])


# --- 正常系 ------------------------------------------------------------------
def test_正常系は根拠付きのレポートで終わる():
    row = run("full_report")
    assert (row["stop_reason"], row["outcome"]) == ("done", "report")
    assert (row["steps"], row["llm_calls"], row["tool_calls"]) == (6, 3, 3)
    assert row["state"].threshold == 50_000
    assert [f["expense_id"] for f in row["state"].findings] == ["EXP-0002", "EXP-0004"]
    assert row["score"]["passed"] == 4
    assert row["files"] == ["report.md"]
    text = read_artifact("mid01/report.md")
    assert "| EXP-0002 | 高橋 涼 | 68,000 | 接待交際費 | submitted |" in text
    assert "- 結果: 報告" in text


def test_判定基準はモデルの数字ではなく状態から入る():
    row = run("full_report")
    # シナリオは min_amount=0 で呼んでいるが、規程から取った 50000 に書き換わる
    args = [call.args for step in row["traj"].steps for call in step.calls
            if call.name == "find_expenses"]
    assert args == [{"status": "submitted", "min_amount": 50_000, "limit": 20}]
    assert "find_expenses(limit=20, min_amount=50000, status=submitted)" in row["state"].sources


def test_独立した読み取りだけが並列になる():
    row = run("parallel_reads")
    assert row["batches"] == ["parallel", "serial", "serial"]
    assert (row["llm_calls"], row["tool_calls"], row["outcome"]) == (3, 4, "report")
    # search_docs は根拠に採用しない（信頼境界の外に置く）
    assert list(row["state"].materials) == ["get_policy", "find_expenses"]
    assert row["state"].notes == ["search_docs(limit=1, query=経費精算手順)"]


def test_段階外の道具は実行されず言い直しで回復する():
    row = run("stage_violation")
    assert (row["steps"], row["llm_calls"], row["failed_calls"]) == (7, 4, 1)
    assert row["outcome"] == "report"
    errors = [r.error for step in row["traj"].steps for r in step.results if not r.ok]
    assert "いまは 'collecting' の段階なので" in errors[0]
    assert "この段階で使えるツール: find_expenses, get_policy, search_docs。" in errors[0]


# --- 異常系1：上限到達 -------------------------------------------------------
def test_上限に達したら部分結果を渡す():
    row = run("budget_partial")
    assert (row["stop_reason"], row["outcome"]) == ("max_steps", "partial")
    # planning / collecting×2 / 上限に達したことを記録する1手 / stopping
    assert (row["steps"], row["llm_calls"]) == (5, 2)
    assert row["state"].stopped_at == "collecting"
    text = read_artifact("mid01/report.md")
    assert "- 結果: 打ち切り（部分結果）" in text
    assert "そろっていない材料: find_expenses" in text
    assert "判定: していない" in text
    assert row["score"]["passed"] == 4  # 打ち切りでも渡すものは渡せている


def test_上限で止めたのはシナリオが尽きたからではない():
    case = CASES["budget_partial"]
    # シナリオはまだ3手目を持っている。止めたのは上限である
    assert len(case.turns) == 3
    assert run("budget_partial")["llm_calls"] == 2


# --- 異常系2：道具の失敗 -----------------------------------------------------
def test_直せない道具の失敗は人へ渡す():
    row = run("broken_tool")
    assert (row["stop_reason"], row["outcome"]) == ("error", "handoff")
    assert (row["steps"], row["llm_calls"], row["failed_calls"]) == (4, 2, 1)
    assert "内部エラー（TimeoutError）" in row["state"].handoff_reason
    assert row["files"] == ["handoff.md"]
    assert "- 結果: 引き継ぎ" in read_artifact("mid01/handoff.md")


def test_直せる失敗は同じ段階で言い直す():
    row = run("no_evidence")
    # get_policy の失敗は S04 の is_actionable を満たすので、いったん言い直させる
    assert row["llm_calls"] == 2
    assert row["stop_reason"] == "done"


# --- 異常系3：情報不足 -------------------------------------------------------
def test_根拠に使えない規程では判定しない():
    row = run("wrong_policy")
    assert (row["stop_reason"], row["outcome"]) == ("done", "insufficient")
    assert (row["steps"], row["llm_calls"]) == (4, 1)
    assert row["state"].threshold is None
    text = read_artifact("mid01/report.md")
    assert "- 結果: 情報不足" in text
    assert "判定: していない（「該当なし」ではない）" in text


def test_調べる手が尽きたら情報不足として渡す():
    row = run("no_evidence")
    assert row["outcome"] == "insufficient"
    assert (row["steps"], row["tool_calls"], row["failed_calls"]) == (4, 2, 1)
    text = read_artifact("mid01/report.md")
    assert "そろっていない材料: get_policy, find_expenses" in text
    assert "- （採用できた根拠はありません）" in text


# --- 報告の裏取り ------------------------------------------------------------
def test_根拠にない報告は差し戻され2回で人へ渡る():
    row = run("hallucination_guarded")
    assert (row["stop_reason"], row["outcome"]) == ("loop_detected", "handoff")
    assert (row["steps"], row["llm_calls"]) == (9, 4)
    assert len(row["state"].rejected) == LOOP_LIMITS["reporting"]
    assert row["files"] == ["handoff.md", "report.md"]


def test_同じ状態を2回繰り返しても入力は増える():
    row = run("hallucination_guarded")
    tokens = row["input_tokens"]
    assert tokens == sorted(tokens) and len(set(tokens)) == len(tokens)


def test_照合を外すと嘘の報告がそのまま通る():
    bare = run("hallucination_bare")
    assert (bare["stop_reason"], bare["outcome"]) == ("done", "report")
    assert bare["score"]["passed"] == 3
    assert bare["score"]["missing"] == ["書かれた申請IDがすべて根拠にある"]
    guarded = run("hallucination_guarded")
    # 同じシナリオ・同じ道具で、違いは照合の有無だけ
    assert guarded["case"].turns == bare["case"].turns


# --- 計画の検査 --------------------------------------------------------------
def test_正しい計画には違反が無い():
    assert check_plan(RESEARCH_PLAN, build_registry().names()) == []


def test_状態が割り当てられていないサブゴールを検出する():
    violations = check_plan(PLAN_UNMAPPED, build_registry().names())
    assert len(violations) == 1
    assert "sg_wrapup" in violations[0]
    assert "実行する状態が割り当てられていません" in violations[0]


def test_その状態で使えない道具を検出する():
    violations = check_plan(PLAN_FORBIDDEN, build_registry().names())
    assert any("未登録のツール 'send_message'" in v for v in violations)
    assert any("状態 'drafting' では使えません" in v for v in violations)


def test_計画が検査に落ちたら1手も動かない():
    row = run("invalid_plan")
    assert (row["stop_reason"], row["outcome"]) == ("error", "handoff")
    assert (row["steps"], row["llm_calls"]) == (2, 0)
    assert row["files"] == ["handoff.md"]


def test_サブゴールと状態は1対1で対応する():
    assert set(SUBGOAL_STATES) == {sg.id for sg in RESEARCH_PLAN.subgoals}
    assert all(state in TRANSITIONS for state in SUBGOAL_STATES.values())


# --- 部品の単体テスト --------------------------------------------------------
@pytest.mark.parametrize(("text", "expected"), [
    ("経費精算: 領収書を添付し、支出日から10日以内に申請する。1件5万円以上は事前承認が必要。",
     50_000),
    ("会議室予約: 連続利用は4時間まで。10名以上の会議は大会議室を優先する。", None),
    ("上限は 30,000 円とする。", 30_000),
    ("", None),
])
def test_規程から判定基準を取り出す(text, expected):
    assert extract_threshold(text) == expected


def test_表から該当行だけを拾う():
    table = ("該当 3 件（表示 3 件）\n"
             "EXP-0004 | 佐藤 健 | 145000 | 出張旅費 | submitted\n"
             "EXP-0006 | 鈴木 彩 | 52000 | 接待交際費 | approved\n"
             "EXP-0001 | 佐藤 健 | 3200 | 交通費 | submitted")
    assert [r["expense_id"] for r in find_findings(table, 50_000)] == ["EXP-0004"]


def test_根拠にない識別子だけを返す():
    assert ungrounded_ids("EXP-0002 と EXP-0009", "EXP-0002 | 高橋 涼") == ["EXP-0009"]


# --- 決定性 ------------------------------------------------------------------
@pytest.mark.parametrize("name", ["full_report", "budget_partial", "broken_tool"])
def test_2回走らせて同じ軌跡と同じ成果物になる(name):
    first = run(name)
    text_first = read_artifact("mid01/report.md") + read_artifact("mid01/handoff.md")
    second = run(name)
    text_second = read_artifact("mid01/report.md") + read_artifact("mid01/handoff.md")
    assert first["traj"].tool_names == second["traj"].tool_names
    assert first["input_tokens"] == second["input_tokens"]
    assert (first["stop_reason"], first["outcome"]) == (second["stop_reason"],
                                                        second["outcome"])
    assert text_first == text_second
