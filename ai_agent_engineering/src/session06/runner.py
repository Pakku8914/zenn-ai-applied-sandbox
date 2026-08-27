#!/usr/bin/env python3
"""セッション6：状態機械で走り、チェックポイントから再開できる実行器。

セッション3の `ReActAgent` との違いは1点だけである。
**「次に何をしてよいか」をモデルではなく状態が決める。**

  - 状態ごとに使えるツールを絞る（段階を飛ばした操作は実行前に止まる）
  - 何をもって次へ進むかは状態から導く（`_derive_event`）
  - 1ステップ進むたびにチェックポイントを保存する（途中から再開できる）

`agentkit` は1行も変更していない。`agentkit.state.Machine` と `Checkpoint` を
そのまま使い、足りない部分（状態ごとの許可リスト・ループ上限・write-ahead）を
この層で足している。
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import DATA  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402
from agentkit.models import (LLMResponse, Step, ToolCall, ToolResult,  # noqa: E402
                            Trajectory)
from agentkit.state import Checkpoint  # noqa: E402
from states import (CHECKPOINT_STATES, LOOP_LIMITS, MATERIAL_TOOLS,  # noqa: E402
                    REQUIRED_SOURCES, SLOTS, STATE_TOOLS, TERMINAL, THRESHOLD,
                    TaskState, build_machine, find_violations, render_report)

DEFAULT_DIR = ROOT / "traces" / "checkpoints" / "session06"


class SimulatedCrash(RuntimeError):
    """プロセスが落ちたことを再現する例外（演習で意図的に投げる）。"""


# ---------------------------------------------------------------------------
# 会話履歴の組み立てと、軌跡の表示
# ---------------------------------------------------------------------------
def build_messages(task: str, traj: Trajectory, view: dict | None = None) -> list[dict]:
    """会話履歴を軌跡から組み立て直す（セッション3と同じ考え方）。

    状態は `view`（状態の投影）として system に**毎回作り直して**渡す。
    プロンプトの文字列に進捗を積み上げていくのではないところが要点。
    ツールを呼ばなかったステップは履歴に足さない。進捗は view が伝えるので、
    思考を積み上げる必要がないためである。
    """
    messages: list[dict] = []
    if view is not None:
        messages.append({"role": "system",
                         "content": "現在の状態:\n"
                                    + json.dumps(view, ensure_ascii=False, indent=2)})
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


def llm_calls(traj: Trajectory) -> int:
    """手数（＝LLM を呼んだ回数）。状態から自動で決めたステップは数えない。"""
    return sum(1 for s in traj.steps if s.usage.get("llm", 1))


def render_run(traj: Trajectory) -> str:
    """1行1ステップで「どの状態で何をして、どこへ遷移したか」を表示する。"""
    lines = [f"task_id={traj.task_id} stop_reason={traj.stop_reason} "
             f"手数={len(traj.steps)}"]
    for s in traj.steps:
        state = s.usage.get("state", "?")
        event = s.usage.get("event") or "（遷移なし）"
        if s.calls:
            action = " ".join(f"{c.name}:{'ok' if r.ok else 'NG'}"
                              for c, r in zip(s.calls, s.results))
        elif not s.usage.get("llm", 1):
            action = "（モデル呼び出しなし）"
        else:
            action = "（ツールなし）"
        batch = s.usage.get("batch")
        suffix = f" [{batch}]" if batch else ""
        lines.append(f"  step {s.index} <{state}> {action}{suffix} -> {event}")
    lines.append(f"  final: {traj.final}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
class ResumableRunner:
    """状態機械で進み、チェックポイントから再開できる実行器。

    granularity … "step"（毎ステップ保存）/ "subgoal"（節目だけ保存）
    guard       … "none"（何もしない）/ "ahead"（副作用の前に意図を保存する）
    auto_states … モデルに聞かず状態から決める状態（LLM 呼び出しを節約する）
    """

    def __init__(self, llm, tools, *, task_id: str = "TASK-006", max_steps: int = 12,
                 threshold: int = THRESHOLD, granularity: str = "step",
                 guard: str = "none", auto_states: tuple[str, ...] = (),
                 clock=None, checkpoint_dir: Path | None = None) -> None:
        if granularity not in ("step", "subgoal"):
            raise ValueError(f"granularity は step か subgoal です: {granularity!r}")
        if guard not in ("none", "ahead"):
            raise ValueError(f"guard は none か ahead です: {guard!r}")
        self.llm = llm
        self.tools = tools
        self.specs = tools.specs()
        self.task_id = task_id
        self.max_steps = max_steps
        self.threshold = threshold
        self.granularity = granularity
        self.guard = guard
        self.auto_states = tuple(auto_states)
        self.clock = clock or FixedClock()
        self.dir = Path(checkpoint_dir) if checkpoint_dir else DEFAULT_DIR
        self.saves = 0
        self.state: TaskState | None = None
        self.trajectory: Trajectory | None = None

    # -- 走行 ---------------------------------------------------------------
    def run(self, task: str, *, resume: bool = False, crash_at: int | None = None,
            crash_before_save: int | None = None) -> Trajectory:
        if resume:
            checkpoint = Checkpoint.load(self.task_id, self.dir)
            traj = checkpoint.trajectory
            st = TaskState.from_dict(checkpoint.state)
            machine = build_machine(st.state)
            self._settle_pending(traj, st, machine)
            self._sync_oracle(st.llm_calls)
        else:
            traj = Trajectory(task_id=self.task_id, task=task)
            st = TaskState(task_id=self.task_id, threshold=self.threshold)
            machine = build_machine()
        self.state = st
        self.trajectory = traj

        while True:
            state = machine.state

            # ① 強制終了の注入。ここまでの保存はすべて済んでいる
            if crash_at is not None and len(traj.steps) == crash_at:
                raise SimulatedCrash(f"step {crash_at} の直前で強制終了しました")

            # ② 終端。done なら最終回答を作り、failed はそのまま終わる
            if state in TERMINAL:
                if state == "failed":
                    if traj.stop_reason == "done":
                        traj.stop_reason = "error"
                    self._save(traj, st, force=True)
                    return traj
                return self._finish(task, traj, st)

            # ③ 打ち切りは「行動の前」に判定する（セッション3と同じ順序）
            if len(traj.steps) >= self.max_steps:
                traj.stop_reason = "max_steps"
                self._save(traj, st, force=True)
                return traj
            limit = LOOP_LIMITS.get(state)
            if limit is not None and st.visits.get(state, 0) >= limit:
                machine.fire("fatal")
                st.state = machine.state
                traj.stop_reason = "loop_detected"
                traj.final = (f"状態 '{state}' に {limit} 回留まったので打ち切りました。"
                              "先に進む条件を満たせていません。")
                self._save(traj, st, force=True)
                return traj

            st.visits[state] = st.visits.get(state, 0) + 1

            # ④ 思考。auto_states ならモデルに聞かない
            try:
                res = self._ask(state, task, traj, st)
            except SimulatedCrash:
                raise
            except Exception as exc:  # noqa: BLE001
                traj.stop_reason = "error"
                traj.final = f"LLM 呼び出しに失敗しました: {type(exc).__name__}: {exc}"
                self._save(traj, st, force=True)  # ここまでは再開できる
                return traj

            step = Step(index=len(traj.steps), thought=res.thought,
                        usage={"input_tokens": res.input_tokens,
                               "output_tokens": res.output_tokens,
                               "state": state, "event": "",
                               "llm": 0 if state in self.auto_states else 1})

            # ⑤ 行動。状態が許すツールだけを実行する
            calls, results = self._execute(state, st, res.calls, traj, step)
            step.calls.extend(calls)
            step.results.extend(results)
            self._apply(state, st, calls, results)
            traj.steps.append(step)

            # ⑥ 遷移。次の状態は「状態と結果」から決める
            event = self._derive_event(state, st, results)
            machine.fire(event)
            st.state = machine.state
            step.usage["event"] = event

            # ⑦ 保存。副作用を出したあとにここで落ちるのが一番厄介なケース
            if crash_before_save is not None and step.index == crash_before_save:
                raise SimulatedCrash(
                    f"step {step.index} を実行したが、保存する前に落ちました")
            self._save(traj, st, prev=state)

    # -- 終端の処理 ---------------------------------------------------------
    def _finish(self, task: str, traj: Trajectory, st: TaskState) -> Trajectory:
        res = self._ask("done", task, traj, st)
        step = Step(index=len(traj.steps), thought=res.thought,
                    usage={"input_tokens": res.input_tokens,
                           "output_tokens": res.output_tokens,
                           "state": "done", "event": "",
                           "llm": 0 if "done" in self.auto_states else 1})
        traj.steps.append(step)
        traj.final = res.final if res.final is not None else res.thought
        traj.stop_reason = "done"
        self._save(traj, st, force=True)
        return traj

    # -- 思考 ---------------------------------------------------------------
    def _ask(self, state: str, task: str, traj: Trajectory, st: TaskState) -> LLMResponse:
        if state in self.auto_states:
            return LLMResponse(thought=f"（{state} は決定的な判断なのでモデルに聞かない）")
        res = self.llm.respond(build_messages(task, traj, st.prompt_view()), self.specs)
        st.llm_calls += 1  # 何回聞いたかも状態に含める（再開位置をここから復元する）
        return res

    def _sync_oracle(self, position: int) -> None:
        """再開時にオラクルの位置を状態に合わせる。

        実モデルは状態を持たず「同じ履歴を渡せば同じ次の一手を返す」。
        `ScriptedClient` の `cursor` はその性質を決定的に再現するための代役なので、
        再開時には「これまでに何回聞いたか」に合わせておく。
        合わせ忘れると最初の一手からやり直しになる（実モデルでも、履歴を渡し忘れると
        同じ事故が起きる）。
        """
        if hasattr(self.llm, "cursor"):
            self.llm.cursor = position

    # -- 行動 ---------------------------------------------------------------
    def _execute(self, state: str, st: TaskState, calls: list[ToolCall],
                 traj: Trajectory, step: Step) -> tuple[list[ToolCall], list[ToolResult]]:
        allowed = STATE_TOOLS.get(state, ())
        ordered: list[ToolCall] = []
        to_run: list[ToolCall] = []
        for call in calls:
            if call.name in allowed:
                rewritten = self._rewrite(st, call)
                ordered.append(rewritten)
                to_run.append(rewritten)
            else:
                ordered.append(call)  # 拒否する呼び出しは書き換えず、そのまま軌跡に残す

        done: dict[str, ToolResult] = {}
        if to_run:
            for call in to_run:
                self._write_ahead(traj, st, call, step.index)
            if len(to_run) > 1 and all(self._read_only(c) for c in to_run):
                # 読み取り専用だけを並列にする。map は入力順に返すので軌跡は決定的
                with ThreadPoolExecutor(max_workers=len(to_run)) as pool:
                    outputs = list(pool.map(self.tools.call, to_run))
                step.usage["batch"] = "parallel"
            else:
                outputs = [self.tools.call(c) for c in to_run]
                step.usage["batch"] = "serial"
            for call, result in zip(to_run, outputs):
                done[call.call_id] = result
                self._after_effect(st, call, result)

        results: list[ToolResult] = []
        for call in ordered:
            if call.call_id in done:
                results.append(done[call.call_id])
            else:
                results.append(ToolResult(
                    call.call_id, False, "",
                    f"いまは '{state}' の段階なので、ツール '{call.name}' は実行できません。"
                    f"この段階で使えるツール: {', '.join(allowed) if allowed else 'なし'}。"))
        return ordered, results

    def _rewrite(self, st: TaskState, call: ToolCall) -> ToolCall:
        """モデルの提案を状態で上書きする。

        - レポート本文は状態から組み立てる（モデルの文章に依存させない）
        - 予約する枠は状態が持つ候補から選ぶ（言い直しに任せない）
        """
        args = dict(call.args)
        if call.name == "write_file" and args.get("content") == "__REPORT__":
            args["content"] = render_report(st)
        if call.name == "book_room":
            args.setdefault("room", "みなと")
            args["start"] = SLOTS[min(st.slot_index, len(SLOTS) - 1)]
        if args == call.args:
            return call
        return ToolCall(call.call_id, call.name, args)

    def _read_only(self, call: ToolCall) -> bool:
        tool = self.tools.get(call.name)
        return tool is not None and "read" in tool.tags

    def _effect_key(self, call: ToolCall) -> str:
        return f"{call.name}:{json.dumps(call.args, ensure_ascii=False, sort_keys=True)}"

    def _write_ahead(self, traj: Trajectory, st: TaskState, call: ToolCall,
                     step_index: int) -> None:
        """副作用を出す前に「これから実行する」を保存する。"""
        if self.guard != "ahead":
            return
        tool = self.tools.get(call.name)
        if tool is None or tool.idempotent:
            return
        st.pending = {"tool": call.name, "args": dict(call.args), "step": step_index}
        self._save(traj, st, force=True)

    def _after_effect(self, st: TaskState, call: ToolCall, result: ToolResult) -> None:
        tool = self.tools.get(call.name)
        if tool is not None and not tool.idempotent and result.ok:
            st.done_keys.append(self._effect_key(call))
        if st.pending is not None and st.pending.get("tool") == call.name:
            st.pending = None

    # -- 状態の更新と遷移 ---------------------------------------------------
    def _apply(self, state: str, st: TaskState, calls: list[ToolCall],
               results: list[ToolResult]) -> None:
        for call, result in zip(calls, results):
            if not result.ok:
                continue
            if call.name in MATERIAL_TOOLS:
                st.materials[call.name] = result.content
            if call.name == "write_file":
                st.report_path = call.args.get("path")
            if call.name == "book_room":
                st.booking = {"room": call.args.get("room"), "start": call.args.get("start")}
        if state == "checking":
            st.violations = find_violations(st.materials.get("list_expenses", ""),
                                            st.threshold)
        if state == "rescheduling":
            st.slot_index += 1

    def _derive_event(self, state: str, st: TaskState, results: list[ToolResult]) -> str:
        ok = any(r.ok for r in results)
        if state == "planning":
            return "plan_ready"
        if state == "collecting":
            return ("collected" if all(k in st.materials for k in REQUIRED_SOURCES)
                    else "need_more")
        if state == "checking":
            return "violation_found" if st.violations else "no_violation"
        if state == "drafting":
            return "draft_saved" if ok else "fatal"
        if state == "booking":
            return "booked" if ok else "conflict"
        if state == "rescheduling":
            return "slot_chosen" if st.slot_index < len(SLOTS) else "no_slot"
        if state == "wrapping_up":
            return "reported" if ok else "fatal"
        raise ValueError(f"遷移を決められない状態です: {state!r}")

    # -- 保存と再開 ---------------------------------------------------------
    def _save(self, traj: Trajectory, st: TaskState, *, prev: str | None = None,
              force: bool = False) -> bool:
        if not force and self.granularity == "subgoal":
            if st.state == prev or st.state not in CHECKPOINT_STATES:
                return False
        Checkpoint(task_id=self.task_id, trajectory=traj, state=st.to_dict()).save(self.dir)
        self.saves += 1
        return True

    def _settle_pending(self, traj: Trajectory, st: TaskState, machine) -> None:
        """保存前に落ちた副作用の始末をする。

        `pending` が残っていたら、その操作は「実行されたかもしれない」。
        やり直す前に外部の記録を照合し、済んでいれば実行せず先へ進める。
        """
        pending = st.pending
        st.pending = None
        if not pending:
            return
        if not self._already_done(pending):
            # 実行されていなかった。この手はやり直すので、聞いた回数も1つ戻す
            # （意図を保存したのはモデルに聞いたあとなので、1手ぶん先に進んでいる）
            if pending.get("step") == len(traj.steps):
                st.llm_calls = max(0, st.llm_calls - 1)
            return
        call = ToolCall(f"settle-{pending['step']}", pending["tool"], pending["args"])
        result = ToolResult(call.call_id, True,
                            "既に実行済みでした（外部の記録に一致する行があります）。"
                            "二重実行を避けました。")
        step = Step(index=len(traj.steps),
                    thought="（再開）保存前に落ちた操作を外部の記録と照合する。",
                    calls=[call], results=[result],
                    usage={"state": machine.state, "event": "", "llm": 0,
                           "batch": "settle"})
        self._apply(machine.state, st, [call], [result])
        event = self._derive_event(machine.state, st, [result])
        machine.fire(event)
        st.state = machine.state
        step.usage["event"] = event
        traj.steps.append(step)
        self._save(traj, st, force=True)

    def _already_done(self, pending: dict) -> bool:
        """外部の記録を見て、その操作が済んでいるかを確かめる。

        照合できる操作に限る。照合できない相手には、冪等キーを受け付けてもらう
        （セッション4の冪等キー・セッション11の再試行設計）しか手がない。
        """
        if pending.get("tool") != "book_room":
            return False
        args = pending.get("args", {})
        path = DATA / "bookings.jsonl"
        if not path.exists():
            return False
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            if (row.get("room") == args.get("room")
                    and row.get("start") == args.get("start")
                    and row.get("date") == self.clock.today()):
                return True
        return False


if __name__ == "__main__":
    from agentkit.biztools import build_registry
    from agentkit.llm import ScriptedClient
    from scenarios import RESEARCH

    TASK = ("経費精算の規程を確認し、規程に照らして問題のある申請を洗い出して"
            "レポートにまとめ、報告会の会議室を予約してください")
    runner = ResumableRunner(ScriptedClient(RESEARCH), build_registry())
    print(render_run(runner.run(TASK)))
