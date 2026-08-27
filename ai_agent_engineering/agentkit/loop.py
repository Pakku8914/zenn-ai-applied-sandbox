"""ReAct ループ（セッション3の参照実装）。

意図的に「足りない」状態で置いている（requirements.md の「わざと残す欠け」）:
  - 再試行しない（セッション11で読者が実装する）
  - 承認を強制しない（セッション10で読者が組み込む）
  - 履歴を圧縮しない（セッション7でコンテキストが溢れる）
"""

from __future__ import annotations

from dataclasses import dataclass

from .clock import FixedClock
from .models import Step, ToolResult, Trajectory
from .tools import ToolRegistry


@dataclass
class Budget:
    """コストと手数の上限（セッション16で使う）。"""

    max_input_tokens: int = 200_000
    max_output_tokens: int = 20_000
    max_tool_calls: int = 40

    def exceeded(self, traj: Trajectory) -> bool:
        total = traj.total_tokens
        return (total["input"] > self.max_input_tokens
                or total["output"] > self.max_output_tokens
                or len(traj.tool_names) > self.max_tool_calls)


class ApprovalRequired(Exception):
    """承認が必要な操作に到達したことを表す（セッション10で使う）。"""

    def __init__(self, call) -> None:
        super().__init__(f"承認が必要です: {call.name}")
        self.call = call


class ReActAgent:
    """観測 → 思考 → 行動 を繰り返す最小のエージェント。"""

    def __init__(self, llm, tools: ToolRegistry, *, max_steps: int = 8,
                 budget: Budget | None = None, clock=None, tracer=None,
                 approval=None, system: str = "") -> None:
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.budget = budget
        self.clock = clock or FixedClock()
        self.tracer = tracer
        self.approval = approval
        self.system = system

    def run(self, task: str, task_id: str = "TASK-001",
            resume: Trajectory | None = None) -> Trajectory:
        traj = resume or Trajectory(task_id=task_id, task=task)
        messages = self._rebuild_messages(task, traj)
        specs = self.tools.specs()

        while True:
            if len(traj.steps) >= self.max_steps:
                traj.stop_reason = "max_steps"
                return traj
            if self.budget and self.budget.exceeded(traj):
                traj.stop_reason = "budget"
                return traj

            span = self.tracer.span("llm", step=len(traj.steps)) if self.tracer else _NullSpan()
            with span:
                try:
                    res = self.llm.respond(messages, specs)
                except Exception as exc:  # noqa: BLE001
                    # LLM 側の失敗は軌跡に残して終わる（再試行はセッション11で足す）
                    traj.stop_reason = "error"
                    traj.final = f"LLM 呼び出しに失敗しました: {type(exc).__name__}: {exc}"
                    return traj

            step = Step(index=len(traj.steps), thought=res.thought,
                        usage={"input_tokens": res.input_tokens,
                               "output_tokens": res.output_tokens})

            if not res.calls:
                # ツールを呼ばない＝最終回答
                step.results = []
                traj.steps.append(step)
                traj.final = res.final if res.final is not None else res.thought
                traj.stop_reason = "done"
                return traj

            for call in res.calls:
                step.calls.append(call)
                tool = self.tools.get(call.name)
                if self.approval is not None and tool is not None and tool.requires_approval:
                    decision = self.approval.check(call, traj)
                    if decision is None:  # まだ承認されていない
                        traj.steps.append(step)
                        traj.stop_reason = "awaiting_approval"
                        return traj
                    if decision is False:
                        step.results.append(ToolResult(
                            call.call_id, False, "",
                            "この操作は承認されませんでした。別の方法を検討してください。"))
                        continue
                with (self.tracer.span("tool", tool=call.name) if self.tracer else _NullSpan()):
                    step.results.append(self.tools.call(call))

            traj.steps.append(step)
            messages = self._rebuild_messages(task, traj)

    def _rebuild_messages(self, task: str, traj: Trajectory) -> list[dict]:
        """会話履歴を軌跡から組み立て直す。

        履歴を状態として持たず毎回作り直すのは、チェックポイントから再開したときに
        同じ履歴が再現されるようにするため（セッション6の伏線）。
        """
        messages: list[dict] = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        messages.append({"role": "user", "content": task})
        for s in traj.steps:
            if s.calls:
                messages.append({
                    "role": "assistant",
                    "content": ([{"type": "text", "text": s.thought}] if s.thought else [])
                    + [{"type": "tool_use", "id": c.call_id, "name": c.name, "input": c.args}
                       for c in s.calls],
                })
                messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": r.call_id,
                                 "content": r.content if r.ok else (r.error or ""),
                                 "is_error": not r.ok}
                                for r in s.results],
                })
        return messages


class _NullSpan:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
