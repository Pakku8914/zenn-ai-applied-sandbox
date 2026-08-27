#!/usr/bin/env python3
"""軌跡テストのシナリオ（成果物④の材料）。

    python src/mid01/cases.py     # 全シナリオを走らせて1行ずつ表示する

9通りの走行を用意した。正常系3本・異常系5本・比較用1本である。
異常系には**上限到達・道具の失敗・情報不足**の3つを必ず入れる。この3つに答えが
あるかどうかが、このプロジェクトの評価観点そのものだからである。

| 名前 | 何を確かめるか | 結果 |
| :--- | :--- | :--- |
| full_report            | 正常系（収集2巡 → 報告）              | report |
| parallel_reads         | 独立した読み取りを並列にする          | report |
| stage_violation        | 段階外の道具を断り、言い直して回復する  | report |
| budget_partial         | 手数の上限に達したら部分結果を渡す      | partial |
| wrong_policy           | 根拠に使えない規程を取ってしまった      | insufficient |
| no_evidence            | 調べる手が尽きた（情報不足）            | insufficient |
| broken_tool            | 直せない道具の失敗（内部エラー）        | handoff |
| hallucination_guarded  | 根拠にない申請IDを2回書いたので人へ渡す | handoff |
| hallucination_bare     | 比較用。照合を外すと嘘の報告が通る      | report |
| invalid_plan           | 計画が検査に落ちたら1手も動かない      | handoff |
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field

from _paths import setup

ROOT = setup()

from agentkit.llm import ScriptedClient  # noqa: E402

from agent import TASK, ResearchAgent, llm_calls, render_run  # noqa: E402
from analysis import artifact_path, artifacts_on_disk, read_artifact  # noqa: E402
from research_plan import PLAN_UNMAPPED, RESEARCH_PLAN  # noqa: E402
from score import score_run  # noqa: E402
from spec import build_breaking_registry, build_registry  # noqa: E402


def call(name: str, **args) -> dict:
    return {"name": name, "args": args}


EXPENSES_CALL = call("find_expenses", status="submitted", min_amount=0, limit=20)

FULL_REPORT = [
    {"thought": "判定基準を先に確定させる。金額の基準は規程から取る。",
     "calls": [call("get_policy", topic="経費精算")]},
    {"thought": "基準額以上で未承認の申請だけに絞って取る。",
     "calls": [EXPENSES_CALL]},
    {"thought": "根拠を添えて報告する。",
     "final": "基準額（50,000円）以上で事前承認の記録がない申請は EXP-0002"
              "（68,000円・接待交際費）と EXP-0004（145,000円・出張旅費）の2件です。"
              "詳細は workspace/mid01/report.md に保存しました。"},
]

PARALLEL_READS = [
    {"thought": "規程と手順書は互いに独立に読める。まとめて取る。",
     "calls": [call("get_policy", topic="経費精算"),
               call("search_docs", query="経費精算手順", limit=1)]},
    {"thought": "基準額以上で未承認の申請を取る。",
     "calls": [EXPENSES_CALL]},
    {"thought": "根拠を添えて報告する。",
     "final": "事前承認の記録がない申請は EXP-0002 と EXP-0004 の2件です。"
              "手順書の記載とも矛盾しません。"},
]

STAGE_VIOLATION = [
    {"thought": "先にレポートの雛形を書いておく。",
     "calls": [call("write_file", path="mid01/report.md", content="（雛形）")]},
    {"thought": "その段階では書けないと言われた。先に規程を読む。",
     "calls": [call("get_policy", topic="経費精算")]},
    {"thought": "基準額以上で未承認の申請を取る。",
     "calls": [EXPENSES_CALL]},
    {"thought": "報告する。",
     "final": "EXP-0002 と EXP-0004 の2件に事前承認の記録がありません。"},
]

BUDGET_PARTIAL = [
    {"thought": "規程と手順書をまとめて読む。",
     "calls": [call("get_policy", topic="経費精算"),
               call("search_docs", query="経費精算手順", limit=1)]},
    {"thought": "注記の書き方も確認しておく。",
     "calls": [call("search_docs", query="規程違反の注記", limit=1)]},
    # この手は使われない。止めたのはシナリオの尽きではなく上限である
    {"thought": "申請の一覧を取る。", "calls": [EXPENSES_CALL]},
]

WRONG_POLICY = [
    {"thought": "規程と申請一覧をまとめて取る。",
     "calls": [call("get_policy", topic="会議室予約"), EXPENSES_CALL]},
    {"thought": "報告する。", "final": "（この手は使われない）"},
]

NO_EVIDENCE = [
    {"thought": "海外出張旅費の規程を読む。",
     "calls": [call("get_policy", topic="海外出張旅費")]},
    {"thought": "該当する規程が無い。これ以上調べる手がない。",
     "final": "判定基準となる規程が見つかりませんでした。"},
]

BROKEN_TOOL = [
    {"thought": "規程を読む。", "calls": [call("get_policy", topic="経費精算")]},
    {"thought": "申請の一覧を取る。", "calls": [EXPENSES_CALL]},
]

HALLUCINATION = [
    {"thought": "規程を読む。", "calls": [call("get_policy", topic="経費精算")]},
    {"thought": "申請の一覧を取る。", "calls": [EXPENSES_CALL]},
    {"thought": "報告する。",
     "final": "EXP-0009 と EXP-0011 の2件に事前承認の記録がありません。"},
    {"thought": "もう一度報告する。",
     "final": "EXP-0009 に事前承認の記録がありません。"},
]


@dataclass(frozen=True)
class Case:
    name: str
    label: str
    turns: tuple = field(default_factory=tuple)
    max_llm_calls: int = 6
    guard: bool = True
    broken: tuple = ()
    plan: object = RESEARCH_PLAN


CASES = (
    Case("full_report", "正常系（収集2巡）", tuple(FULL_REPORT)),
    Case("parallel_reads", "並列読み取り", tuple(PARALLEL_READS)),
    Case("stage_violation", "段階外の道具を断る", tuple(STAGE_VIOLATION)),
    Case("budget_partial", "上限到達（部分結果）", tuple(BUDGET_PARTIAL), max_llm_calls=2),
    Case("wrong_policy", "根拠に使えない規程", tuple(WRONG_POLICY)),
    Case("no_evidence", "情報不足（手が尽きた）", tuple(NO_EVIDENCE)),
    Case("broken_tool", "直せない道具の失敗", tuple(BROKEN_TOOL),
         broken=("find_expenses",)),
    Case("hallucination_guarded", "根拠にない報告を差し戻す", tuple(HALLUCINATION)),
    Case("hallucination_bare", "比較用：照合を外す", tuple(HALLUCINATION), guard=False),
    Case("invalid_plan", "計画が検査に落ちる", (), plan=PLAN_UNMAPPED),
)


def reset_data() -> None:
    """業務データを初期状態に戻す（決定的なので何度でも呼べる）。

    他のセッションの演習が経費を追加していると、該当件数が変わって数値が合わない。
    測る前に必ず戻す。
    """
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


def by_name() -> dict:
    return {case.name: case for case in CASES}


def run_case(case: Case) -> dict:
    """1本走らせて、比較に使う数字をまとめて返す。"""
    registry = build_breaking_registry(case.broken) if case.broken else build_registry()
    agent = ResearchAgent(
        ScriptedClient({"name": case.name, "turns": list(case.turns)}),
        registry, task_id=f"TASK-M01-{case.name}", plan=case.plan,
        max_llm_calls=case.max_llm_calls, guard=case.guard,
    )
    traj = agent.run(TASK)
    st = agent.state
    results = [r for step in traj.steps for r in step.results]
    return {
        "case": case,
        "traj": traj,
        "state": st,
        "registry": registry,
        "steps": len(traj.steps),
        "llm_calls": llm_calls(traj),
        "stages": llm_calls(traj),   # 単体構成なので段数＝手数（S08 の数え方）
        "tool_calls": len(traj.tool_names),
        "failed_calls": sum(1 for r in results if not r.ok),
        "stop_reason": traj.stop_reason,
        "outcome": st.outcome,
        "score": score_run(st, traj),
        "files": artifacts_on_disk(),
        # 成果物の本文は**この走行の直後に**読む（次の走行が上書きするため）
        "artifact_text": read_artifact(artifact_path(st.outcome)),
        "batches": [step.usage.get("batch") for step in traj.steps
                    if step.usage.get("batch")],
        "input_tokens": [step.usage.get("input_tokens", 0) for step in traj.steps
                         if step.usage.get("llm", 1)],
        "output_tokens": [step.usage.get("output_tokens", 0) for step in traj.steps
                          if step.usage.get("llm", 1)],
    }


def run_all() -> list[dict]:
    reset_data()
    return [run_case(case) for case in CASES]


def main() -> None:
    for row in run_all():
        case = row["case"]
        print(f"=== {case.name}（{case.label}） ===")
        print(render_run(row["traj"]))
        print(f"  結果={row['outcome']} 採点={row['score']['passed']}/"
              f"{row['score']['total']} 残ったファイル={row['files']}")
        print()


if __name__ == "__main__":
    main()
