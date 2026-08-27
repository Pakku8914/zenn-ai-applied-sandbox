#!/usr/bin/env python3
"""調査エージェント（成果物③）。

    python src/mid01/agent.py     # 正常系を1本走らせて軌跡を表示する

セッション3の `ReActAgent` との違いは1点だけである。
**次に何をしてよいかを、モデルではなく状態が決める**（セッション6）。

`agentkit` は1行も変更していない。足したのは次の4つだけ。

  1. 状態ごとの許可リスト（S04 の許可リストを状態に紐づける）
  2. 判定基準の抽出と、道具の引数の書き換え（基準にモデルの数字を使わない）
  3. 根拠の照合（報告文の申請IDが、採用した根拠に現れるか）
  4. 3つの終わり方（上限到達・道具の失敗・情報不足）

上限に達したとき・道具が失敗したとき・根拠がそろわないときに何が起きるかは、
この1ファイルを読めば分かるようにしてある。それがこのプロジェクトの評価観点である。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from _paths import setup

ROOT = setup()

from agentkit.clock import FixedClock  # noqa: E402
from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: E402
from goodtools import is_actionable  # noqa: E402  (S04)

from analysis import (artifact_text, clear_artifacts, extract_threshold,  # noqa: E402
                      find_findings, summary_line)
from machine import (ARTIFACT_PATH, HANDOFF_PATH, LOOP_LIMITS,  # noqa: E402
                     MATERIAL_TOOLS, STATE_TOOLS, TERMINAL, ResearchState,
                     build_machine, stage_error)
from research_plan import RESEARCH_PLAN, check_plan  # noqa: E402
from score import ungrounded_ids  # noqa: E402
from spec import build_registry  # noqa: E402

TASK = ("経費精算の規程を確認し、規程に照らして事前承認の記録がない申請を洗い出して、"
        "根拠付きのレポートにまとめてください")


class LLMFailure(RuntimeError):
    """モデル側の失敗（例外・タイムアウト）。道具の失敗とは別に扱う。"""


def llm_calls(traj: Trajectory) -> int:
    """手数＝モデルを呼んだ回数。状態から自動で決めた手は数えない。"""
    return sum(1 for step in traj.steps if step.usage.get("llm", 1))


def fmt_args(args: dict) -> str:
    """出典として記録する引数の書き方。並びを固定して比較できるようにする。"""
    return ", ".join(f"{key}={args[key]}" for key in sorted(args))


def build_messages(task: str, traj: Trajectory, view: dict) -> list[dict]:
    """会話履歴を軌跡から組み立て直す（S03・S06 と同じ考え方）。

    状態は `view`（状態の投影）として system に**毎回作り直して**渡す。
    ツールを呼ばなかったステップは履歴に足さない（進捗は view が伝える）。
    """
    messages: list[dict] = [
        {"role": "system",
         "content": "現在の状態:\n" + json.dumps(view, ensure_ascii=False, indent=2)},
        {"role": "user", "content": task},
    ]
    for step in traj.steps:
        if not step.calls:
            continue
        messages.append({
            "role": "assistant",
            "content": ([{"type": "text", "text": step.thought}] if step.thought else [])
            + [{"type": "tool_use", "id": c.call_id, "name": c.name, "input": c.args}
               for c in step.calls],
        })
        messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": r.call_id,
                         "content": r.content if r.ok else (r.error or ""),
                         "is_error": not r.ok}
                        for r in step.results],
        })
    return messages


def render_run(traj: Trajectory) -> str:
    """1行1ステップで「どの状態で何をして、どこへ遷移したか」を表示する。"""
    lines = [f"task_id={traj.task_id} stop_reason={traj.stop_reason} "
             f"ステップ={len(traj.steps)} 手数={llm_calls(traj)}"]
    for step in traj.steps:
        state = step.usage.get("state", "?")
        event = step.usage.get("event") or "（遷移なし）"
        if step.calls:
            action = " ".join(f"{c.name}:{'ok' if r.ok else 'NG'}"
                              for c, r in zip(step.calls, step.results))
        elif step.usage.get("llm", 1):
            action = "（ツールなし）"
        else:
            action = "（モデル呼び出しなし）"
        batch = step.usage.get("batch")
        lines.append(f"  step {step.index} <{state}> {action}"
                     f"{f' [{batch}]' if batch else ''} -> {event}")
    lines.append(f"  final: {traj.final}")
    return "\n".join(lines)


class ResearchAgent:
    """状態機械で進む調査エージェント。

    guard=False にすると根拠の照合を外す（比較用。悪い実装の再現）。
    """

    def __init__(self, llm, tools=None, *, task_id: str = "TASK-M01",
                 plan=RESEARCH_PLAN, max_llm_calls: int = 6, max_steps: int = 16,
                 guard: bool = True, clock=None) -> None:
        self.llm = llm
        self.tools = tools if tools is not None else build_registry()
        self.specs = self.tools.specs()
        self.task_id = task_id
        self.plan = plan
        self.max_llm_calls = max_llm_calls
        self.max_steps = max_steps
        self.guard = guard
        self.clock = clock or FixedClock()
        self.state: ResearchState | None = None
        self.trajectory: Trajectory | None = None

    # -- 走行 ---------------------------------------------------------------
    def run(self, task: str = TASK) -> Trajectory:
        clear_artifacts()
        traj = Trajectory(task_id=self.task_id, task=task)
        st = ResearchState(task_id=self.task_id, max_llm_calls=self.max_llm_calls)
        machine = build_machine()
        self.state, self.trajectory = st, traj

        while True:
            state = machine.state
            st.state = state

            # ① 終端。done なら成果物は出ている。failed は引き継ぎ済み
            if state in TERMINAL:
                return traj

            # ② 上限は「行動の前」に判定する（S03 と同じ順序）
            if self._over_limit(traj) and machine.can("over_budget"):
                traj.stop_reason = "max_steps"
                st.outcome = "partial"
                st.stopped_at = state
                self._auto(traj, st, machine, state, "over_budget",
                           f"手数の上限 {self.max_llm_calls} 回に達した。"
                           "ここまでの結果を渡して止まる。")
                continue

            # ③ 同じ状態に留まりすぎたら打ち切る（ループには必ず上限を置く）
            limit = LOOP_LIMITS.get(state)
            if (limit is not None and st.visits.get(state, 0) >= limit
                    and machine.can("blocked")):
                traj.stop_reason = "loop_detected"
                self._escalate(st, state,
                               f"状態 '{state}' に {limit} 回留まりました。"
                               "同じ段階の繰り返しでは先に進めません。")
                self._auto(traj, st, machine, state, "blocked", st.handoff_reason)
                continue

            st.visits[state] = st.visits.get(state, 0) + 1

            # ④ その状態の処理を1ステップだけ進める
            try:
                getattr(self, f"_do_{state}")(traj, st, machine)
            except LLMFailure as exc:
                traj.stop_reason = "error"
                self._escalate(st, state, f"モデルの呼び出しに失敗しました（{exc}）。")
                if machine.can("blocked"):
                    self._auto(traj, st, machine, state, "blocked", st.handoff_reason)
                    continue
                traj.final = st.handoff_reason
                return traj

    def _over_limit(self, traj: Trajectory) -> bool:
        """手数の上限とステップ数の安全網。手数が主で、ステップ数は保険。"""
        return (llm_calls(traj) >= self.max_llm_calls
                or len(traj.steps) >= self.max_steps)

    def _escalate(self, st: ResearchState, state: str, reason: str) -> None:
        st.outcome = "handoff"
        st.handoff_reason = reason
        st.stopped_at = state

    # -- ステップの作りかた -------------------------------------------------
    def _new_step(self, traj: Trajectory, state: str, res=None, *, llm: int) -> Step:
        return Step(index=len(traj.steps),
                    thought=(res.thought if res is not None else ""),
                    usage={"input_tokens": res.input_tokens if res is not None else 0,
                           "output_tokens": res.output_tokens if res is not None else 0,
                           "state": state, "event": "", "llm": llm})

    def _finish_step(self, traj: Trajectory, st: ResearchState, machine, step: Step,
                     event: str) -> None:
        traj.steps.append(step)
        machine.fire(event)
        st.state = machine.state
        step.usage["event"] = event

    def _auto(self, traj: Trajectory, st: ResearchState, machine, state: str,
              event: str, thought: str) -> None:
        """モデルを呼ばずに1ステップ進める（手数に数えない）。"""
        step = self._new_step(traj, state, None, llm=0)
        step.thought = thought
        self._finish_step(traj, st, machine, step, event)

    def _ask(self, task: str, traj: Trajectory, st: ResearchState):
        try:
            res = self.llm.respond(build_messages(task, traj, st.prompt_view()), self.specs)
        except Exception as exc:  # noqa: BLE001
            raise LLMFailure(f"{type(exc).__name__}: {exc}") from exc
        st.llm_calls += 1
        return res

    # -- 行動 ---------------------------------------------------------------
    def _read_only(self, call: ToolCall) -> bool:
        tool = self.tools.get(call.name)
        return tool is not None and "read" in tool.tags

    def _rewrite(self, st: ResearchState, call: ToolCall) -> ToolCall:
        """モデルの提案を状態で上書きする。

        判定基準の金額は**状態が持つ値**を使う。モデルが書いた数字を使うと、
        規程を読んだのに違う基準で数えた報告が出る（しかも見た目は正しい）。
        """
        if call.name == "find_expenses" and st.threshold is not None:
            args = dict(call.args)
            args["min_amount"] = st.threshold
            if args != call.args:
                return ToolCall(call.call_id, call.name, args)
        return call

    def _execute(self, state: str, st: ResearchState, calls: list[ToolCall],
                 step: Step) -> tuple[list[ToolCall], list[ToolResult]]:
        """状態が許すツールだけを実行する。拒否した呼び出しも軌跡に残す。"""
        allowed = STATE_TOOLS.get(state, ())
        ordered: list[ToolCall] = []
        to_run: list[ToolCall] = []
        for call in calls:
            if call.name in allowed:
                rewritten = self._rewrite(st, call)
                ordered.append(rewritten)
                to_run.append(rewritten)
            else:
                ordered.append(call)

        done: dict[str, ToolResult] = {}
        if to_run:
            if len(to_run) > 1 and all(self._read_only(c) for c in to_run):
                # 読み取り専用だけを並列にする。map は入力順に返すので軌跡は決定的
                with ThreadPoolExecutor(max_workers=len(to_run)) as pool:
                    outputs = list(pool.map(self.tools.call, to_run))
                step.usage["batch"] = "parallel"
            else:
                outputs = [self.tools.call(call) for call in to_run]
                step.usage["batch"] = "serial"
            done = {call.call_id: result for call, result in zip(to_run, outputs)}

        results: list[ToolResult] = []
        for call in ordered:
            if call.call_id in done:
                results.append(done[call.call_id])
            else:
                results.append(ToolResult(call.call_id, False, "",
                                          stage_error(state, call.name, allowed)))
        return ordered, results

    def _absorb(self, st: ResearchState, calls: list[ToolCall],
                results: list[ToolResult]) -> None:
        """成功した読み取り結果を状態に取り込む。取り込むものは宣言で決める。"""
        for call, result in zip(calls, results):
            if not result.ok:
                continue
            label = f"{call.name}({fmt_args(call.args)})"
            if call.name in MATERIAL_TOOLS:
                st.materials[call.name] = result.content
                st.sources.append(label)
            else:
                # 根拠に採用しない結果は状態に入れない（信頼境界。S12 への布石）
                st.notes.append(label)
            if call.name == "get_policy":
                st.threshold = extract_threshold(result.content)

    def _write_artifact(self, state: str, st: ResearchState, step: Step, path: str,
                        text: str) -> ToolResult:
        call = ToolCall(f"auto-{step.index}", "write_file", {"path": path, "content": text})
        calls, results = self._execute(state, st, [call], step)
        step.calls.extend(calls)
        step.results.extend(results)
        if results[0].ok:
            st.artifact = path
        return results[0]

    # -- 状態ごとの処理 -----------------------------------------------------
    def _do_planning(self, traj: Trajectory, st: ResearchState, machine) -> None:
        """計画を実行前に検査する。落ちたら1手もモデルを呼ばない。"""
        violations = check_plan(self.plan, self.tools.names())
        step = self._new_step(traj, "planning", None, llm=0)
        step.thought = f"計画を実行前に検査した（違反 {len(violations)} 件）。"
        if violations:
            traj.stop_reason = "error"
            self._escalate(st, "planning",
                           "計画が実行前の検査に通りませんでした: " + " / ".join(violations))
            self._finish_step(traj, st, machine, step, "invalid_plan")
            return
        self._finish_step(traj, st, machine, step, "plan_ready")

    def _do_collecting(self, traj: Trajectory, st: ResearchState, machine) -> None:
        """材料を集める。次に何を調べるかだけをモデルに決めさせる。"""
        res = self._ask(traj.task, traj, st)
        step = self._new_step(traj, "collecting", res, llm=1)
        calls, results = self._execute("collecting", st, res.calls, step)
        step.calls.extend(calls)
        step.results.extend(results)
        self._absorb(st, calls, results)

        failures = [r for r in results if not r.ok]
        if not st.missing_sources():
            event = "collected"
        elif failures and not all(is_actionable(r.error or "") for r in failures):
            # 次の行動を決められない失敗。言い直しても直らないので人へ渡す
            traj.stop_reason = "error"
            self._escalate(st, "collecting",
                           "道具の失敗から次の行動を決められません: "
                           + " / ".join(r.error or "" for r in failures))
            event = "blocked"
        elif failures:
            event = "need_more"
        elif not calls:
            # モデルが「これ以上調べる手がない」と申告した。終わったかは状態が決める
            event = "not_found"
        else:
            event = "need_more"
        self._finish_step(traj, st, machine, step, event)

    def _do_checking(self, traj: Trajectory, st: ResearchState, machine) -> None:
        """根拠として使えるかを確かめる。ここはモデルに聞かない。"""
        step = self._new_step(traj, "checking", None, llm=0)
        if st.threshold is None:
            step.thought = "規程から判定基準の金額を読み取れなかった。判定できない。"
            st.outcome = "insufficient"
            st.stopped_at = "checking"
            self._finish_step(traj, st, machine, step, "ungrounded")
            return
        st.findings = find_findings(st.materials.get("find_expenses", ""), st.threshold)
        step.thought = (f"判定基準 {st.threshold:,} 円で照合した"
                        f"（該当 {len(st.findings)} 件）。")
        self._finish_step(traj, st, machine, step, "grounded")

    def _do_drafting(self, traj: Trajectory, st: ResearchState, machine) -> None:
        """レポート本文を状態から組み立てて保存する。モデルには書かせない。"""
        step = self._new_step(traj, "drafting", None, llm=0)
        step.thought = "レポート本文を状態から組み立てて保存する。"
        result = self._write_artifact("drafting", st, step, ARTIFACT_PATH,
                                      artifact_text("report", st))
        if result.ok:
            st.outcome = "report"
            self._finish_step(traj, st, machine, step, "draft_saved")
            return
        traj.stop_reason = "error"
        self._escalate(st, "drafting", f"レポートを保存できませんでした: {result.error}")
        self._finish_step(traj, st, machine, step, "blocked")

    def _do_reporting(self, traj: Trajectory, st: ResearchState, machine) -> None:
        """報告の1文だけをモデルに書かせ、根拠と照合してから採用する。"""
        res = self._ask(traj.task, traj, st)
        step = self._new_step(traj, "reporting", res, llm=1)
        text = res.final if res.final is not None else res.thought
        ungrounded = self._ungrounded_ids(st, text)
        if self.guard and ungrounded:
            reason = (f"報告文の {', '.join(ungrounded)} は採用した根拠にありません。"
                      "根拠にある申請IDだけを書いてください。")
            st.rejected.append(reason)
            step.thought = f"報告文を差し戻した（{reason}）"
            self._finish_step(traj, st, machine, step, "hallucinated")
            return
        traj.final = text
        st.outcome = "report"
        self._finish_step(traj, st, machine, step, "reported")

    def _ungrounded_ids(self, st: ResearchState, text: str) -> list[str]:
        """報告文の識別子のうち、採用した根拠に現れないものを返す。

        採点（`score.py`）と同じ関数を使う。評価に使う基準と、走行中に使う基準を
        別々に書くと、必ずどちらかがずれる。
        """
        return ungrounded_ids(text, "\n".join(st.materials.values()))

    def _do_insufficient(self, traj: Trajectory, st: ResearchState, machine) -> None:
        """情報不足の申し送りを残して終わる。「該当なし」とは書かない。"""
        step = self._new_step(traj, "insufficient", None, llm=0)
        step.thought = "根拠がそろわない。何が足りないかを書いて渡す。"
        st.outcome = "insufficient"
        result = self._write_artifact("insufficient", st, step, ARTIFACT_PATH,
                                      artifact_text("insufficient", st))
        traj.final = summary_line(st, "insufficient")
        if result.ok:
            self._finish_step(traj, st, machine, step, "reported")
            return
        traj.stop_reason = "error"
        self._escalate(st, "insufficient", f"申し送りを保存できませんでした: {result.error}")
        self._finish_step(traj, st, machine, step, "blocked")

    def _do_stopping(self, traj: Trajectory, st: ResearchState, machine) -> None:
        """上限で打ち切ったときの部分結果を残して終わる。"""
        step = self._new_step(traj, "stopping", None, llm=0)
        step.thought = "上限で打ち切った。ここまでの結果と残りの作業を書いて渡す。"
        st.outcome = "partial"
        result = self._write_artifact("stopping", st, step, ARTIFACT_PATH,
                                      artifact_text("partial", st))
        traj.final = summary_line(st, "partial")
        if result.ok:
            self._finish_step(traj, st, machine, step, "partial_saved")
            return
        self._escalate(st, "stopping", f"部分結果を保存できませんでした: {result.error}")
        self._finish_step(traj, st, machine, step, "blocked")

    def _do_handoff(self, traj: Trajectory, st: ResearchState, machine) -> None:
        """人へ渡す。書けても書けなくても、走行はここで終える。"""
        step = self._new_step(traj, "handoff", None, llm=0)
        step.thought = "人に渡す。何が起きたかと、次に何をすべきかを1枚にする。"
        st.outcome = "handoff"
        self._write_artifact("handoff", st, step, HANDOFF_PATH,
                             artifact_text("handoff", st))
        traj.final = summary_line(st, "handoff")
        self._finish_step(traj, st, machine, step, "escalated")


def main() -> None:
    """正常系を1本だけ走らせる（シナリオ一覧は cases.py にある）。"""
    from agentkit.llm import ScriptedClient  # noqa: PLC0415

    turns = [
        {"thought": "判定基準を先に確定させる。金額の基準は規程から取る。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "基準額以上で未承認の申請だけに絞って取る。",
         "calls": [{"name": "find_expenses",
                    "args": {"status": "submitted", "min_amount": 0, "limit": 20}}]},
        {"thought": "根拠を添えて報告する。",
         "final": "EXP-0002 と EXP-0004 の2件に事前承認の記録がありません。"},
    ]
    agent = ResearchAgent(ScriptedClient({"name": "demo", "turns": turns}),
                          task_id="TASK-M01-demo")
    traj = agent.run(TASK)
    print(render_run(traj))
    print()
    print(f"結果={agent.state.outcome} 手数={llm_calls(traj)} "
          f"出典={agent.state.sources}")


if __name__ == "__main__":
    main()
