#!/usr/bin/env python3
"""セッション5の実測（すべて決定的）。本文の数値はこのスクリプトの出力。

    python src/session05/measure.py

近似トークン数は「文字数 ÷ 3」の比較用の値であり、実 API の課金額ではない。
実行の前後で tools/make_data.py を走らせるので、何度実行しても同じ結果になる。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: E402
from impact import REPORT_CHECKS, impact_facts, score_report  # noqa: E402
from planner import (PlanError, SubGoal, mermaid_dag, parse_plan,  # noqa: E402
                     plan_cost, render_plan_md, topo_layers, validate_plan)
from plans import (PLAN_CYCLE, PLAN_FRAGMENTED, PLAN_NOT_JSON, PLAN_OK,  # noqa: E402
                   PLAN_OVERSPLIT, TURNS_BUDGET, TURNS_EVERY, TURNS_FRAGMENTED,
                   TURNS_NEWFACT, TURNS_REPLAN, TURNS_STATIC_BROKEN, TURNS_STATIC_OK,
                   plan_from, plan_json)
from runner import RunResult, run_noplan, run_planned, should_replan  # noqa: E402

BUDGET_CALLS = 12


def reset_data() -> None:
    """業務データを初期状態に戻す（決定的なので何度でも呼べる）。"""
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


def run_all() -> dict[str, RunResult]:
    """5つの方式＋2つの比較用を同じタスクで走らせる。"""
    reset_data()
    return {
        "noplan": run_noplan("計画なし"),
        "static_ok": run_planned("静的計画（前提が正しい）", TURNS_STATIC_OK,
                                 replan_policy="never"),
        "static_broken": run_planned("静的計画（前提が誤り）", TURNS_STATIC_BROKEN,
                                     replan_policy="never"),
        "replan": run_planned("逐次再計画", TURNS_REPLAN, replan_policy="on_trigger"),
        "budget": run_planned("逐次再計画＋予算", TURNS_BUDGET, replan_policy="on_trigger",
                              budget_calls=BUDGET_CALLS),
        "every": run_planned("毎サブゴール再計画", TURNS_EVERY,
                             replan_policy="every_subgoal", max_replans=10),
        "fragmented": run_planned("分解しすぎ（依存を書き忘れ）", TURNS_FRAGMENTED,
                                  replan_policy="never", enforce_validation=False),
    }


def run_newfact() -> RunResult:
    """新情報トリガでサブゴールを1つ足す実行（問題8）。比較表とは別に測る。"""
    reset_data()
    return run_planned("新情報（却下済みを検出）", TURNS_NEWFACT,
                       replan_policy="on_trigger", watch_facts=("rejected",))


def scored(res: RunResult) -> tuple[int, list[str]]:
    return score_report(res.report)


def validation_cases() -> list[tuple[str, list[str]]]:
    """実行前検証。壊れた計画を実行しないで止められるかを見る。"""
    tools = build_registry().names()
    cases: list[tuple[str, list[str]]] = []
    for label, raw in (("過分解（サブゴール10個）", PLAN_OVERSPLIT),
                       ("依存が循環している計画", PLAN_CYCLE),
                       ("分解しすぎ（依存を書き忘れ）", PLAN_FRAGMENTED),
                       ("正しい計画", PLAN_OK)):
        cases.append((label, validate_plan(plan_from(raw), tools)))
    try:
        parse_plan(PLAN_NOT_JSON)
    except PlanError as exc:
        cases.append(("JSON でない計画（パース時に落ちる）", [str(exc)]))
    return cases


def _fake_traj(*, ok: bool, content: str) -> Trajectory:
    """トリガ判定の単体確認用に、結果だけを持つ軌跡を組み立てる。"""
    traj = Trajectory(task_id="TASK-005-trigger", task="トリガの確認")
    result = (ToolResult("c0", True, content) if ok
              else ToolResult("c0", False, "", content))
    traj.steps.append(Step(index=0, thought="", calls=[ToolCall("c0", "list_expenses", {})],
                           results=[result], usage={"input_tokens": 0, "output_tokens": 0}))
    return traj


def trigger_cases() -> list[tuple[str, str | None]]:
    """3つのトリガと「立たない場合」を1つずつ確かめる。"""
    rest = [SubGoal(id="sg_rest", goal="残りの仕事", max_steps=2)]
    ok_traj = _fake_traj(ok=True, content="EXP-0005 | 渡辺 陽 | 4400 | 交通費 | rejected")
    fail_traj = _fake_traj(ok=False, content="'経費精算規程' の規程は見つかりません。")
    return [
        ("失敗（ツール結果が失敗）",
         should_replan(fail_traj, pending=rest, used_calls=3)),
        ("新情報（計画が触れていない語が結果に出た）",
         should_replan(ok_traj, pending=rest, used_calls=3,
                       plan_text="申請一覧を取得する", watch_facts=("rejected",))),
        ("予算（残りで計画を実行しきれない）",
         should_replan(ok_traj, pending=rest, used_calls=5, budget_calls=6)),
        ("どれも立たない（作り直さない）",
         should_replan(ok_traj, pending=rest, used_calls=3, budget_calls=20)),
    ]


def main() -> None:
    print("==============================================")
    print(" セッション5：計画と分解の実測（すべて決定的）")
    print("==============================================")

    facts = impact_facts()
    print()
    print("=== 1. 実データから計算した影響（基準日 2026-08-15）===")
    print(f"- 新たに事前承認が必要: {len(facts['newly_approval'])} 件 / "
          f"すでに対象: {len(facts['already_approval'])} 件")
    print(f"- 新たに期限超過: {len(facts['newly_late'])} 件 / "
          f"元から超過: {len(facts['already_late'])} 件")

    plan_ok = plan_from(PLAN_OK)
    print()
    print("=== 2. 計画（構造として持つ）===")
    print(render_plan_md(plan_ok))
    for i, layer in enumerate(topo_layers(plan_ok)):
        print(f"- 層{i}（同時に走らせられる）: {', '.join(sg.id for sg in layer)}")
    print(f"- 計画のコスト: {plan_cost(plan_ok)}")
    print(f"- 計画 JSON の長さ: {len(plan_json(PLAN_OK))} 文字")

    runs = run_all()
    print()
    print("=== 3. 方式の比較（同じタスク・同じ台本・制御構造だけを変える）===")
    header = (f"{'方式':<26}{'計画':>5}{'手数':>5}{'LLM':>5}{'ツール':>7}"
              f"{'失敗':>5}{'近似in':>8}{'近似out':>8}{'点':>5}{'停止理由':>14}")
    print(header)
    print("-" * len(header))
    for res in runs.values():
        score, _ = scored(res)
        total = res.total_tokens
        print(f"{res.label:<26}{res.plan_calls:>5}{res.exec_steps:>5}{res.llm_calls:>5}"
              f"{res.tool_calls:>7}{res.failed_tool_calls:>5}{total['input']:>8}"
              f"{total['output']:>8}{score:>3}/{len(REPORT_CHECKS)}{res.stop_reason:>14}")
    print()
    for res in runs.values():
        score, missing = scored(res)
        print(f"- {res.label}: {res.report_path or '（成果物なし）'} / "
              f"{score}/{len(REPORT_CHECKS)} 点"
              + (f" / 欠けた観点: {', '.join(missing)}" if missing else " / 欠けなし"))

    print()
    print("=== 3b. 新情報トリガ（計画にサブゴールを1つ足す）===")
    nf = run_newfact()
    nf_score, _ = scored(nf)
    print(f"- {nf.label}: 計画 {nf.plan_calls} / 手数 {nf.exec_steps} / "
          f"LLM {nf.llm_calls} / ツール {nf.tool_calls} / "
          f"{nf_score}/{len(REPORT_CHECKS)} 点 / {nf.stop_reason}")
    for reason in nf.replans:
        print(f"    - {reason}")
    print(f"- 呼んだツール: {', '.join(nf.tool_names)}")

    print()
    print("=== 4. 再計画のログ（何をきっかけに作り直したか）===")
    for key in ("replan", "budget", "every"):
        res = runs[key]
        print(f"- {res.label}: 再計画 {len(res.replans)} 回 / 計画呼び出し {res.plan_calls} 回")
        for i, reason in enumerate(res.replans, start=1):
            print(f"    {i}. {reason}")

    print()
    print("=== 5. 実行前の検証（壊れた計画を実行しない）===")
    for label, violations in validation_cases():
        print(f"- {label}: 違反 {len(violations)} 件")
        for v in violations:
            print(f"    - {v}")

    print()
    print("=== 6. 再計画のトリガ（単体の判定）===")
    for label, reason in trigger_cases():
        print(f"- {label}: {reason or 'None（作り直さない）'}")

    print()
    print("=== 7. 分解の粒度と計画のコスト ===")
    for label, raw in (("5サブゴール（適切）", PLAN_OK),
                       ("10サブゴール（1手ずつ）", PLAN_OVERSPLIT)):
        cost = plan_cost(plan_from(raw))
        print(f"- {label}: サブゴール {cost['subgoals']} / "
              f"最低 LLM 呼び出し {cost['min_llm_calls']} 回 / "
              f"計画の近似トークン {cost['approx_plan_tokens']}")

    print()
    print("=== 8. 正しい計画の DAG（Mermaid・設計レビューに回せる）===")
    print(mermaid_dag(plan_ok))

    reset_data()


if __name__ == "__main__":
    main()
