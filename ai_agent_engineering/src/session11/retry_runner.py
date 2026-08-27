#!/usr/bin/env python3
"""セッション11：失敗を前提に走る実行器。

セッション3の `ReActAgent` との違いは4点だけである。

  1. 一時的な失敗を再試行する（LLM 側もツール側も）
  2. 冪等でない操作は「実行されたか分からない」まま再送しない
  3. 同じ行動の繰り返しを検出して打ち切る
  4. 上限に達したら `on_limit`（fail / partial / handoff）の形で返す

`agentkit` は1行も変更していない。`ReActAgent` に足りない部分をこの層で足す。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.clock import FixedClock  # noqa: E402
from agentkit.models import (LLMResponse, Step, ToolCall, ToolResult,  # noqa: E402
                            Trajectory)
from backoff import RecordingSleeper, backoff_delay  # noqa: E402
from failure_kinds import (HANDOFF, RETRY_ALTERED, RETRY_SAME,  # noqa: E402
                           TRANSIENT, classify_exception, retry_decision)
from guards import (RunLimits, brief_call, call_key, detect_loop,  # noqa: E402
                    handoff_report, render_limit_final, uncertain_effects)


class RetriesExhausted(RuntimeError):
    """再試行しても回復しなかったことを表す。何回試して何秒待ったかを持つ。"""

    def __init__(self, last: BaseException, attempts: int, waited: float) -> None:
        super().__init__(f"{type(last).__name__}: {last}")
        self.last = last
        self.attempts = attempts
        self.waited = waited


def llm_calls(traj: Trajectory) -> int:
    """手数（＝LLM を呼んだ回数）。**再試行も1回として数える**。

    セッション6と同じ定義（`usage["llm"]` の合計）。再試行を数えないと、
    信頼性のために払っているコストが軌跡から消える。
    """
    return sum(s.usage.get("llm", 1) for s in traj.steps)


def build_messages(task: str, traj: Trajectory, system: str = "") -> list[dict]:
    """会話履歴を軌跡から組み立て直す（セッション3と同じ）。"""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": task})
    for s in traj.steps:
        if not s.calls:
            continue
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


def render_run(traj: Trajectory) -> str:
    """1行1ステップで「何をして、何回試して、何秒待ったか」を表示する。"""
    lines = [f"task_id={traj.task_id} stop_reason={traj.stop_reason} "
             f"ステップ={len(traj.steps)} 手数={llm_calls(traj)}"]
    for s in traj.steps:
        if s.calls:
            action = " ".join(f"{c.name}:{'ok' if r.ok else 'NG'}"
                              for c, r in zip(s.calls, s.results))
        else:
            action = "（ツールなし）"
        event = s.usage.get("event") or "-"
        lines.append(f"  step {s.index} {action} llm={s.usage.get('llm', 1)} "
                     f"tool_attempts={s.usage.get('tool_attempts', 0)} "
                     f"waited={s.usage.get('waited', 0.0)} -> {event}")
    lines.append(f"  final: {(traj.final or '').splitlines()[0] if traj.final else None}")
    return "\n".join(lines)


class ReliableRunner:
    """失敗を前提に走る実行器。

    max_retries … 1回の呼び出しを何回まで再試行するか（0 なら再試行しない）
    loop_window … 同じ行動が何回連続したら打ち切るか（0 なら循環検出を切る）
    on_limit    … 上限に達したときの振る舞い（fail / partial / handoff）
    sleeper     … 待機の注入。既定は記録するだけ（実時間では待たない）
    """

    def __init__(self, llm, tools, *, limits: RunLimits | None = None,
                 max_retries: int = 1, sleeper=None, clock=None,
                 loop_window: int = 3, on_limit: str = "fail",
                 task_id: str = "TASK-011", system: str = "") -> None:
        if on_limit not in ("fail", "partial", "handoff"):
            raise ValueError(f"on_limit は fail / partial / handoff です: {on_limit!r}")
        if max_retries < 0:
            raise ValueError("max_retries は0以上で指定してください。")
        self.llm = llm
        self.tools = tools
        self.limits = limits or RunLimits()
        self.max_retries = max_retries
        self.sleeper = sleeper or RecordingSleeper()
        self.clock = clock or FixedClock()
        self.loop_window = loop_window
        self.on_limit = on_limit
        self.task_id = task_id
        self.system = system

    # -- 走行 ---------------------------------------------------------------
    def run(self, task: str) -> Trajectory:
        traj = Trajectory(task_id=self.task_id, task=task)
        specs = self.tools.specs()
        start = self.clock.now()
        keys: list[str] = []

        while True:
            # ① 打ち切りは行動の前に判定する（セッション3と同じ順序）
            elapsed = (self.clock.now() - start).total_seconds()
            hit = self.limits.reached(traj, elapsed=elapsed)
            if hit:
                traj.stop_reason = "max_steps" if hit == "max_steps" else "budget"
                traj.final = render_limit_final(self.on_limit, hit, traj,
                                                self.limits, self.tools)
                return traj

            # ② 思考。一時的な失敗はここで吸収する
            try:
                res, attempts, waited = self._ask(task, traj, specs)
            except RetriesExhausted as exc:
                # 失敗した呼び出しも軌跡に残す（ReActAgent はここを残さない）
                traj.steps.append(Step(
                    index=len(traj.steps), thought="（LLM 呼び出しが回復しなかった）",
                    usage={"input_tokens": 0, "output_tokens": 0, "state": "failing",
                           "event": "llm_error", "llm": exc.attempts, "batch": "serial",
                           "tool_attempts": 0, "waited": round(exc.waited, 3)}))
                traj.stop_reason = "error"
                traj.final = handoff_report(
                    traj, self.tools,
                    reason=f"LLM 呼び出しが {exc.attempts} 回試しても回復しなかった（{exc}）")
                return traj

            step = Step(index=len(traj.steps), thought=res.thought,
                        usage={"input_tokens": res.input_tokens,
                               "output_tokens": res.output_tokens,
                               "state": "running", "event": "", "llm": attempts,
                               "batch": "serial", "tool_attempts": 0,
                               "waited": round(waited, 3)})

            # ③ ツールを呼ばない＝最終回答。ただしモデルの自己申告は信用しない
            if not res.calls:
                traj.steps.append(step)
                unsure = uncertain_effects(traj)
                if unsure:
                    # 実行されたか分からない操作が残っているのに「できました」と
                    # 言われている状態。完了として返すと事故が黙って通る
                    step.usage["event"] = "unverified"
                    traj.stop_reason = "error"
                    traj.final = handoff_report(
                        traj, self.tools,
                        reason="実行されたか分からない操作が残っている")
                else:
                    traj.final = res.final if res.final is not None else res.thought
                    traj.stop_reason = "done"
                return traj

            # ④ 行動。ツール側の失敗も種類で判断する
            for call in res.calls:
                step.calls.append(call)
                result, tries, tool_waited = self._call_tool(call)
                step.results.append(result)
                step.usage["tool_attempts"] += tries
                step.usage["waited"] = round(step.usage["waited"] + tool_waited, 3)
                keys.append(call_key(call))
            traj.steps.append(step)

            # ⑤ 循環の検出は「行動したあと」でしか分からない
            if detect_loop(keys, window=self.loop_window):
                step.usage["event"] = "loop_detected"
                traj.stop_reason = "loop_detected"
                traj.final = handoff_report(
                    traj, self.tools,
                    reason=f"同じ行動の繰り返しを検出した（直近: "
                           f"{brief_call(res.calls[-1])}）")
                return traj

    # -- 思考の再試行 -------------------------------------------------------
    def _ask(self, task: str, traj: Trajectory,
             specs: list[dict]) -> tuple[LLMResponse, int, float]:
        messages = build_messages(task, traj, self.system)
        attempts = 0
        waited = 0.0
        while True:
            attempts += 1
            try:
                return self.llm.respond(messages, specs), attempts, waited
            except Exception as exc:  # noqa: BLE001
                # LLM の呼び出しには副作用がない。だから一時的失敗はそのまま再送できる
                if classify_exception(exc) != TRANSIENT or attempts > self.max_retries:
                    raise RetriesExhausted(exc, attempts, waited) from exc
                delay = backoff_delay(attempts - 1)
                self.sleeper.sleep(delay)
                waited = round(waited + delay, 3)

    # -- 行動の再試行 -------------------------------------------------------
    def _call_tool(self, call: ToolCall) -> tuple[ToolResult, int, float]:
        return retry_guarded(self.tools, call, max_retries=self.max_retries,
                             sleeper=self.sleeper)


def annotate(result: ToolResult, decision) -> ToolResult:
    """モデルに返すエラーに、こちらの判断を1行足す。"""
    if decision.action == HANDOFF:
        note = "この操作は再試行しません。人の確認が必要です。"
    elif decision.action == RETRY_ALTERED:
        note = "同じ引数では通りません。別の引数か別の手段を選んでください。"
    else:
        note = "この操作は再試行しても通りません。"
    return ToolResult(result.call_id, False, "", f"{result.error} {note}")


def retry_guarded(tools, call: ToolCall, *, max_retries: int = 1,
                  sleeper=None) -> tuple[ToolResult, int, float]:
    """判断つきの再試行。失敗の種類と冪等性を見てから決める。"""
    sleeper = sleeper or RecordingSleeper()
    tool = tools.get(call.name)
    idempotent = bool(tool is not None and tool.idempotent)
    attempts = 0
    waited = 0.0
    while True:
        attempts += 1
        result = tools.call(call)
        if result.ok:
            return result, attempts, waited
        decision = retry_decision(result.error or "", idempotent=idempotent,
                                  attempts=attempts, max_retries=max_retries)
        if decision.action != RETRY_SAME:
            # 再試行しないものは、失敗したツール結果としてそのままモデルに返す。
            # 却下・期限切れ（セッション10）と同じ形にそろえておく
            return annotate(result, decision), attempts, waited
        delay = backoff_delay(attempts - 1)
        sleeper.sleep(delay)
        waited = round(waited + delay, 3)


# --- アンチパターン（比較用に残しておく）------------------------------------
def retry_blindly(tools, call: ToolCall, *, max_retries: int = 1,
                  sleeper=None) -> tuple[ToolResult, int, float]:
    """失敗したら種類も冪等性も見ずに再試行する（＝二重申請を作る実装）。"""
    sleeper = sleeper or RecordingSleeper()
    attempts = 0
    waited = 0.0
    while True:
        attempts += 1
        result = tools.call(call)
        if result.ok or attempts > max_retries:
            return result, attempts, waited
        delay = backoff_delay(attempts - 1)
        sleeper.sleep(delay)
        waited = round(waited + delay, 3)


if __name__ == "__main__":
    import subprocess

    from agentkit.biztools import build_registry
    from agentkit.llm import FlakyClient, ScriptedClient
    from retry_scenarios import EXPENSE_SUBMIT, TASK_SUBMIT

    def _reset() -> None:
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                       check=True, capture_output=True)

    _reset()
    llm = FlakyClient(ScriptedClient(EXPENSE_SUBMIT), fail_on=(2,), mode="exception")
    runner = ReliableRunner(llm, build_registry(), max_retries=1)
    print(render_run(runner.run(TASK_SUBMIT)))
    print(f"待機の合計: {runner.sleeper.total} 秒（実時間では待っていません）")
    _reset()
