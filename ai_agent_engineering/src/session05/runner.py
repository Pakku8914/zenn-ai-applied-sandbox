#!/usr/bin/env python3
"""計画を実行する側（計画なし／静的計画／逐次再計画）。

agentkit は1行も変えない。ReActAgent をサブゴール単位で呼び出し、
その外側に「計画を立てる・検証する・作り直す」層を足すだけで3方式を作る。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402
from impact import TASK  # noqa: E402
from plans import noplan_turns, turns_for  # noqa: E402
from planner import (Plan, SubGoal, build_plan_prompt, parse_plan,  # noqa: E402
                     topo_order, validate_plan)


@dataclass
class RunResult:
    """1回の実行の結果。方式の比較に使う数字をここに集める。"""

    label: str
    plan_calls: int = 0          # 計画のために呼んだ LLM の回数
    exec_steps: int = 0          # サブゴール実行のステップ数（＝LLM 呼び出し回数）
    tool_calls: int = 0
    failed_tool_calls: int = 0
    plan_tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0})
    exec_tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0})
    replans: list[str] = field(default_factory=list)
    plans: list[Plan] = field(default_factory=list)
    trajectories: list[Trajectory] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    report: str = ""
    report_path: str = ""
    stop_reason: str = "done"

    @property
    def llm_calls(self) -> int:
        return self.plan_calls + self.exec_steps

    @property
    def total_tokens(self) -> dict:
        return {"input": self.plan_tokens["input"] + self.exec_tokens["input"],
                "output": self.plan_tokens["output"] + self.exec_tokens["output"]}

    @property
    def tool_names(self) -> list[str]:
        return [n for t in self.trajectories for n in t.tool_names]


def request_plan(llm, task: str, tool_names: list[str], context: str = "") -> tuple[Plan, dict]:
    """計画を1回もらう。返ってきた文字列は必ず parse_plan を通す。"""
    messages = [{"role": "user", "content": build_plan_prompt(task, tool_names, context)}]
    res = llm.respond(messages, [])
    plan = parse_plan(res.final if res.final is not None else res.thought)
    return plan, {"input": res.input_tokens, "output": res.output_tokens}


def should_replan(traj: Trajectory, *, pending: list[SubGoal], used_calls: int,
                  budget_calls: int | None = None, plan_text: str = "",
                  watch_facts: tuple[str, ...] = ()) -> str | None:
    """再計画に移るかを判定する。理由（文字列）か None を返す。

    トリガは3つだけに絞る。「何かおかしい気がする」で作り直すと、
    計画のコストが手数と同じだけ増える（本文7節のアンチパターン）。
    """
    # 1. 失敗：ツール結果に失敗がある＝計画の前提が現実と食い違っている
    for step in traj.steps:
        for res in step.results:
            if not res.ok:
                return f"tool_failure: {res.error}"

    # 2. 新情報：計画が触れていない事実が結果に現れた（監視する語は明示的に宣言する）
    for step in traj.steps:
        for res in step.results:
            if not res.ok:
                continue
            for marker in watch_facts:
                if marker in res.content and marker not in plan_text:
                    return f"new_fact: 計画が触れていない '{marker}' が結果に現れました"

    # 3. 予算：残りの呼び出し回数で残りの計画を実行しきれない（+1 は再計画そのものの費用）
    if budget_calls is not None and pending:
        need = sum(sg.max_steps for sg in pending) + 1
        left = budget_calls - used_calls
        if left < need:
            return f"budget: 残り {left} 回に対し、残りの計画は最低 {need} 回必要です"
    return None


def _subgoal_prompt(task: str, sg: SubGoal, facts: dict) -> str:
    context = "\n".join(f"[{k}] {facts[k]}" for k in sg.consumes if k in facts)
    return (f"全体の目的: {task}\n\n"
            f"あなたが担当するサブゴール: {sg.goal}\n\n"
            f"引き継いだ情報:\n{context or '（引き継いだ情報はありません）'}")


def run_subgoal(sg: SubGoal, registry, facts: dict, task: str) -> Trajectory:
    """サブゴール1つを ReActAgent に実行させる。

    ツールは sg.tools だけに絞る（許可リスト方式。セッション4の read_only と同じ考え方）。
    """
    allowed = [t for t in sg.tools if registry.get(t) is not None]
    agent = ReActAgent(
        ScriptedClient({"name": sg.id, "turns": turns_for(sg.id)}),
        registry.subset(allowed),
        max_steps=sg.max_steps,
    )
    return agent.run(_subgoal_prompt(task, sg, facts), task_id=f"TASK-005-{sg.id}")


def _absorb(res: RunResult, traj: Trajectory) -> None:
    res.trajectories.append(traj)
    res.exec_steps += len(traj.steps)
    res.tool_calls += len(traj.tool_names)
    res.failed_tool_calls += sum(1 for s in traj.steps for r in s.results if not r.ok)
    total = traj.total_tokens
    res.exec_tokens["input"] += total["input"]
    res.exec_tokens["output"] += total["output"]
    for step in traj.steps:
        for call in step.calls:
            if call.name == "write_file":
                res.report_path = call.args.get("path", "")
                res.report = call.args.get("content", "")


def run_noplan(label: str = "計画なし", *, registry=None, max_steps: int = 6,
               task: str = TASK) -> RunResult:
    """計画を立てず、1本のループに全部やらせる。"""
    registry = registry or build_registry()
    res = RunResult(label=label)
    agent = ReActAgent(ScriptedClient({"name": "noplan", "turns": noplan_turns()}),
                       registry, max_steps=max_steps)
    traj = agent.run(task, task_id="TASK-005-noplan")
    _absorb(res, traj)
    res.stop_reason = traj.stop_reason
    return res


def run_planned(label: str, planner_turns: list[dict], *, registry=None,
                replan_policy: str = "on_trigger", budget_calls: int | None = None,
                watch_facts: tuple[str, ...] = (), max_replans: int = 3,
                enforce_validation: bool = True, task: str = TASK) -> RunResult:
    """計画を立てて実行する。replan_policy で3方式を切り替える。

    replan_policy:
      never          静的計画（最初に立てた計画を最後まで守る）
      on_trigger     逐次再計画（トリガが立ったときだけ作り直す）
      every_subgoal  毎サブゴール再計画（アンチパターン。コストの比較用）
    """
    if replan_policy not in ("never", "on_trigger", "every_subgoal"):
        raise ValueError(f"不明な replan_policy: {replan_policy}")
    registry = registry or build_registry()
    tool_names = registry.names()
    planner = ScriptedClient({"name": f"planner_{label}", "turns": planner_turns})
    res = RunResult(label=label)

    plan, usage = request_plan(planner, task, tool_names)
    res.plan_calls += 1
    res.plan_tokens["input"] += usage["input"]
    res.plan_tokens["output"] += usage["output"]
    res.plans.append(plan)
    res.violations += validate_plan(plan, tool_names)
    if res.violations and enforce_validation:
        res.stop_reason = "invalid_plan"
        return res

    done: set[str] = set()
    pending = list(topo_order(plan))
    while pending:
        sg = pending.pop(0)
        if budget_calls is not None and res.llm_calls + sg.max_steps > budget_calls:
            res.stop_reason = "budget"
            break

        traj = run_subgoal(sg, registry, res.facts, task)
        _absorb(res, traj)
        done.add(sg.id)
        for key in sg.produces:
            res.facts[key] = traj.final or ""

        reason = should_replan(traj, pending=pending, used_calls=res.llm_calls,
                               budget_calls=budget_calls, plan_text=plan.as_text(),
                               watch_facts=watch_facts)
        wants_replan = bool(pending) and (
            replan_policy == "every_subgoal"
            or (replan_policy == "on_trigger" and reason is not None))
        if not wants_replan or len(res.replans) >= max_replans:
            continue

        res.replans.append(reason or "every_subgoal: 方針として毎サブゴールで作り直す")
        context = (f"完了したサブゴール: {', '.join(sorted(done))}\n"
                   f"手元にある情報: {', '.join(sorted(res.facts))}\n"
                   f"直前の出来事: {reason or 'なし'}")
        plan, usage = request_plan(planner, task, tool_names, context)
        res.plan_calls += 1
        res.plan_tokens["input"] += usage["input"]
        res.plan_tokens["output"] += usage["output"]
        res.plans.append(plan)
        v = validate_plan(plan, tool_names, done=tuple(sorted(done)),
                          known=tuple(sorted(res.facts)))
        res.violations += v
        if v and enforce_validation:
            res.stop_reason = "invalid_plan"
            break
        # 完了したサブゴールは二度実行しない（再計画が同じ仕事をやり直させないため）
        pending = [s for s in topo_order(plan, done=tuple(sorted(done)))
                   if s.id not in done]
    return res
