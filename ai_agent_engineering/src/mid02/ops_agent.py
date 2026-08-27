#!/usr/bin/env python3
"""承認ゲート付き業務エージェント（成果物③）。

    python src/mid02/ops_agent.py     # 正常系を1本走らせる（承認を挟んで再開する）

中間プロジェクト01の調査エージェントとの違いは1点だけである。

> **出す操作が取り返しのつかないものになった。**

そのために足したのは次の5つで、いずれも既習セッションの部品をそのまま使っている。

  1. 隔離実行（S09）… 集計は固定コードだけを隔離コンテナで流す。モデルにコードを書かせない
  2. 承認ゲート（S10）… `awaiting_approval` で中断し、承認後に**同じ状態から**実行する
  3. 引数の確定（S12 の最小権限の延長）… 金額・宛先・冪等キーは計画が決める
  4. 冪等キーと照合（S11）… 実行されたか分からないときは、再送ではなくデータを照合する
  5. 補償（S11）… 却下・失敗・上限で止まるときは、出した副作用を逆順に打ち消す

`agentkit` は1行も変更していない。
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from _paths import setup

ROOT = setup()

from agentkit.approval import call_digest  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402
from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: E402
from agentkit.state import Checkpoint  # noqa: E402
from backoff import RecordingSleeper  # noqa: E402  (S11)
from compensate import cancel_booking, cancel_expense_by_key  # noqa: E402  (S11)
from defenses import mask_secrets  # noqa: E402  (S12)
from failure_kinds import PARTIAL, classify_error, has_alternative  # noqa: E402  (S11)
from gate import ReviewGate  # noqa: E402  (S10)
from goodtools import is_actionable  # noqa: E402  (S04)
from guards import brief_call  # noqa: E402  (S11)
from policy import THRESHOLD_YEN, decide  # noqa: E402  (S10)
from retry_runner import retry_blindly, retry_guarded  # noqa: E402  (S11)

from flow import (ARTIFACT_PATH, HANDOFF_PATH, LOOP_LIMITS,  # noqa: E402
                  MATERIAL_TOOLS, REQUIRED_SOURCES, STATE_TOOLS, TERMINAL,
                  build_machine, stage_error)
from isolated import compute_summary  # noqa: E402
from ledger import already_done, can_match, expense_id_by_key  # noqa: E402
from ops_spec import (OPS_PLAN, UNDO_BY_TOOL, build_tools, check_plan)  # noqa: E402
from writeup import (artifact_body, clear_workspace, summary_line)  # noqa: E402

TASK = ("来週の部門報告会の準備をしてください。会議室を1時間押さえ、懇親会費を申請し、"
        "参加者へ連絡してください。規程に反する内容は実行しないでください")

GATE_DIR = ROOT / "traces" / "approvals" / "mid02"
CHECKPOINT_DIR = ROOT / "traces" / "checkpoints" / "mid02"

MISMATCH_MESSAGE = (
    "承認された内容と実行しようとした内容が一致しません（照合用ハッシュが違います）。"
    "実行していません。承認された内容で実行し直すか、改めて承認を依頼してください。")
ALREADY_MESSAGE = (
    "既に実行済みでした（同じ冪等キーの記録が外部にあります）。二重実行を避けました。")

EXPENSE_ID = re.compile(r"EXP-\d{4}")

# 「5万円」を先に見る（「10日以内」のような数字に引っかからないよう単位ごと拾う）
MAN_YEN = re.compile(r"(\d+)\s*万円")
YEN = re.compile(r"([\d,]+)\s*円")


class LLMFailure(RuntimeError):
    """モデル側の失敗。ツール側の失敗とは別に扱う。"""


def extract_threshold(text: str) -> int | None:
    """規程の本文から判定基準の金額を取り出す。取れなければ None（0 を返さない）。"""
    if not text:
        return None
    hit = MAN_YEN.search(text)
    if hit:
        return int(hit.group(1)) * 10_000
    hit = YEN.search(text)
    if hit:
        return int(hit.group(1).replace(",", ""))
    return None


def llm_calls(traj: Trajectory) -> int:
    """手数＝モデルを呼んだ回数。状態から決めた手は数えない（S11 と同じ数え方）。"""
    return sum(step.usage.get("llm", 1) for step in traj.steps)


def fmt_args(args: dict) -> str:
    return ", ".join(f"{key}={args[key]}" for key in sorted(args))


def build_messages(task: str, traj: Trajectory, view: dict) -> list[dict]:
    """会話履歴を軌跡から組み立て直す（S03・S06・中間プロジェクト01と同じ）。

    状態は `view`（状態の投影）として system に**毎回作り直して**渡す。
    向きは常に 状態 → プロンプト の一方向にする。
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
    """1行1ステップで「どの状態で何をして、どう決着したか」を表示する。"""
    lines = [f"task_id={traj.task_id} stop_reason={traj.stop_reason} "
             f"ステップ={len(traj.steps)} 手数={llm_calls(traj)}"]
    for step in traj.steps:
        state = step.usage.get("state", "?")
        event = step.usage.get("event") or "（決着なし）"
        if step.calls:
            action = " ".join(
                f"{c.name}:{'ok' if i < len(step.results) and step.results[i].ok else 'NG'}"
                for i, c in enumerate(step.calls))
        elif step.usage.get("llm", 1):
            action = "（ツールなし）"
        else:
            action = "（モデル呼び出しなし）"
        mode = step.usage.get("mode")
        lines.append(f"  step {step.index} <{state}> {action}"
                     f"{f' [{mode}]' if mode else ''} -> {event}")
    lines.append(f"  final: {traj.final}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# アプリケーション状態。JSON に落とせる形だけで構成する（S06 と同じ規約）
# ---------------------------------------------------------------------------
@dataclass
class OpsState:
    task_id: str
    state: str = "planning"
    outcome: str = "report"
    threshold: int | None = None
    plan_cursor: int = 0
    visits: dict = field(default_factory=dict)
    alters: dict = field(default_factory=dict)
    materials: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    summary: str = ""
    summary_ref: str = ""
    summary_available: bool = False
    pending: dict | None = None
    effects: list = field(default_factory=list)      # 実行できた副作用（補償の材料）
    done_keys: list = field(default_factory=list)    # 二度押しを弾くための目印
    uncertain: list = field(default_factory=list)    # 実行されたか分からない操作
    blocked_calls: list = field(default_factory=list)  # 出力検査が止めた呼び出し
    offplan: list = field(default_factory=list)      # 計画外の提案
    refusals: list = field(default_factory=list)     # 却下された操作と理由
    compensated: list = field(default_factory=list)
    uncompensated: list = field(default_factory=list)
    handoff_reason: str = ""
    stopped_at: str = ""
    artifact: str = ""
    llm_calls: int = 0
    max_llm_calls: int = 8

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "OpsState":
        return cls(**{key: data[key] for key in data if key in cls.__dataclass_fields__})

    def missing_sources(self) -> list[str]:
        return [name for name in REQUIRED_SOURCES if name not in self.materials]


# ---------------------------------------------------------------------------
class OpsAgent:
    """承認ゲートを挟んで業務を代行するエージェント。

    confirm     … 引数の確定（True なら計画がツールと主要引数を決める）
    use_gate    … 人間承認（False なら承認を挟まない。比較用）
    retry_mode  … guarded（判断つき）/ blind（判断なし。比較用）
    rewrite     … 実行直前に引数を組み立て直す関数（差し替えの再現用）
    isolation   … 隔離実行で集計を付けるか（tool-runner が無い環境では自動で外れる）
    """

    def __init__(self, llm, tools=None, gate=None, *, task_id: str = "TASK-M02",
                 plan=OPS_PLAN, confirm: bool = True, use_gate: bool = True,
                 max_llm_calls: int = 8, max_steps: int = 30, max_alter: int = 1,
                 max_retries: int = 1, retry_mode: str = "guarded", rewrite=None,
                 isolation: bool = True, clock=None, sleeper=None,
                 checkpoint_dir: Path | None = None) -> None:
        if retry_mode not in ("guarded", "blind"):
            raise ValueError(f"retry_mode は guarded か blind です: {retry_mode!r}")
        self.llm = llm
        self.tools = tools if tools is not None else build_tools()[0]
        self.specs = self.tools.specs()
        self.task_id = task_id
        self.plan = tuple(plan)
        self.confirm = confirm
        self.use_gate = use_gate
        self.max_llm_calls = max_llm_calls
        self.max_steps = max_steps
        self.max_alter = max_alter
        self.max_retries = max_retries
        self.retry_mode = retry_mode
        self.rewrite = rewrite
        self.isolation = isolation
        self.clock = clock or FixedClock()
        self.sleeper = sleeper or RecordingSleeper()
        self.dir = Path(checkpoint_dir) if checkpoint_dir else CHECKPOINT_DIR
        self.gate = gate or ReviewGate(task_id, clock=self.clock, directory=GATE_DIR)
        self.state: OpsState | None = None
        self.trajectory: Trajectory | None = None
        self.machine = None
        self.finished = False

    # -- 走行 ---------------------------------------------------------------
    def run(self, task: str = TASK, *, resume: bool = False) -> Trajectory:
        traj, st, machine = self._start(task, resume)
        if self.finished:
            # 終わっている走行は再開しない（承認画面を二度開いても副作用を出さない）
            return traj

        while True:
            state = machine.state
            st.state = state

            # ① 終端
            if state in TERMINAL:
                self._save(traj, st)
                return traj

            # ② 上限は「新しい行動を始める前」に判定する（S03 と同じ順序）。
            #    over_budget の出口を持つのは preparing と requesting だけである。
            #    executing に出口を作ると承認だけが宙に浮き、compensating / reporting /
            #    handoff に作ると後片付けが殺されて、出した副作用が残ったままになる。
            if self._over_limit(traj) and machine.can("over_budget"):
                traj.stop_reason = ("budget" if llm_calls(traj) >= self.max_llm_calls
                                    else "max_steps")
                st.stopped_at = state
                if state == "preparing":
                    st.outcome = "insufficient"
                st.handoff_reason = (f"手数の上限 {self.max_llm_calls} 回に達しました。"
                                     "出した副作用を戻してから渡します。")
                self._auto(traj, st, machine, state, "over_budget", st.handoff_reason)
                continue

            # ③ 同じ状態に留まりすぎたら打ち切る
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
                signal = getattr(self, f"_do_{state}")(traj, st, machine)
            except LLMFailure as exc:
                traj.stop_reason = "error"
                self._escalate(st, state, f"モデルの呼び出しに失敗しました（{exc}）。")
                if machine.can("blocked"):
                    self._auto(traj, st, machine, state, "blocked", st.handoff_reason)
                    continue
                traj.final = st.handoff_reason
                self._save(traj, st)
                return traj
            if signal == "suspend":
                return traj

    def _start(self, task: str, resume: bool):
        if resume:
            checkpoint = Checkpoint.load(self.task_id, self.dir)
            traj = checkpoint.trajectory
            st = OpsState.from_dict(checkpoint.state)
            machine = build_machine(st.state)
            self._sync_oracle(st.llm_calls)
            # 終わっている走行かどうかは、**停止理由を書き換える前に**判定する
            self.finished = (traj.stop_reason != "awaiting_approval"
                             or st.state in TERMINAL)
            if not self.finished:
                # 中断していた走行を再開する。停止理由をいったん既定（done）へ戻し、
                # 新たに止まる理由が生じたときだけ上書きする。
                # ここを戻し忘れると、最後まで走り切っても停止理由が
                # `awaiting_approval` のまま残り、「承認待ちで終わった走行」と
                # 「承認を経て完了した走行」が区別できなくなる。
                traj.stop_reason = "done"
        else:
            self.finished = False
            clear_workspace()
            traj = Trajectory(task_id=self.task_id, task=task)
            st = OpsState(task_id=self.task_id, max_llm_calls=self.max_llm_calls)
            machine = build_machine()
        self.state, self.trajectory, self.machine = st, traj, machine
        return traj, st, machine

    def _over_limit(self, traj: Trajectory) -> bool:
        return (llm_calls(traj) >= self.max_llm_calls
                or len(traj.steps) >= self.max_steps)

    def _escalate(self, st: OpsState, state: str, reason: str) -> None:
        st.handoff_reason = reason
        st.stopped_at = state

    def _sync_oracle(self, position: int) -> None:
        """再開時にオラクルの位置を「これまでに聞いた回数」に合わせる（S06・S10 と同じ）。"""
        if hasattr(self.llm, "cursor"):
            self.llm.cursor = position

    def _save(self, traj: Trajectory, st: OpsState) -> None:
        Checkpoint(task_id=self.task_id, trajectory=traj, state=st.to_dict()).save(self.dir)

    # -- ステップの作りかた -------------------------------------------------
    def _new_step(self, traj: Trajectory, state: str, res=None, *, llm: int) -> Step:
        return Step(index=len(traj.steps),
                    thought=(res.thought if res is not None else ""),
                    usage={"input_tokens": res.input_tokens if res is not None else 0,
                           "output_tokens": res.output_tokens if res is not None else 0,
                           "state": state, "event": "", "llm": llm, "mode": ""})

    def _finish_step(self, traj: Trajectory, st: OpsState, machine, step: Step,
                     event: str) -> None:
        traj.steps.append(step)
        machine.fire(event)
        st.state = machine.state
        step.usage["event"] = event
        self._save(traj, st)

    def _auto(self, traj: Trajectory, st: OpsState, machine, state: str,
              event: str, thought: str) -> None:
        """モデルを呼ばずに1ステップ進める（手数に数えない）。"""
        step = self._new_step(traj, state, None, llm=0)
        step.thought = thought
        self._finish_step(traj, st, machine, step, event)

    def _ask(self, traj: Trajectory, st: OpsState):
        try:
            res = self.llm.respond(build_messages(traj.task, traj, self._view(st)), self.specs)
        except Exception as exc:  # noqa: BLE001
            raise LLMFailure(f"{type(exc).__name__}: {exc}") from exc
        st.llm_calls += 1
        return res

    def _view(self, st: OpsState) -> dict:
        """プロンプトに載せる「状態の投影」。機密は載せない。"""
        step = self.plan[st.plan_cursor] if st.plan_cursor < len(self.plan) else None
        return {
            "現在の段階": st.state,
            "判定基準": f"{st.threshold:,} 円以上は事前承認が必要" if st.threshold else "未確認",
            "そろっていない材料": st.missing_sources(),
            "次に出す操作": ({"操作": step.id, "内容": step.intent, "ツール": step.tool,
                              "あなたが埋めてよい引数": list(step.alterable)}
                             if step else "（すべて出し終えた）"),
            "承認待ち": (f"{st.pending['tool']}（{st.pending.get('mode', '')}）"
                         if st.pending else "なし"),
            "済んだ副作用": [f"{e['tool']}: {e.get('ref') or ''}" for e in st.effects],
            "遮断した試み": list(st.blocked_calls),
            "この段階で使えるツール": list(STATE_TOOLS.get(st.state, ())),
        }

    # -- 行動 ---------------------------------------------------------------
    def _read_only(self, call: ToolCall) -> bool:
        tool = self.tools.get(call.name)
        return tool is not None and "read" in tool.tags

    def _execute(self, state: str, st: OpsState, calls: list[ToolCall],
                 step: Step) -> tuple[list[ToolCall], list[ToolResult]]:
        """状態が許すツールだけを実行する。拒否した呼び出しも軌跡に残す。"""
        allowed = STATE_TOOLS.get(state, ())
        ordered = list(calls)
        to_run = [call for call in ordered if call.name in allowed]

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

    def _absorb(self, st: OpsState, calls: list[ToolCall],
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
                # 根拠に採用しない結果は状態に入れない（信頼境界）
                st.notes.append(label)
            if call.name == "get_policy":
                st.threshold = extract_threshold(result.content)

    def _write_doc(self, state: str, st: OpsState, step: Step, path: str,
                   text: str) -> ToolResult:
        call = ToolCall(f"auto-{step.index}", "write_file",
                        {"path": path, "content": text})
        calls, results = self._execute(state, st, [call], step)
        step.calls.extend(calls)
        step.results.extend(results)
        if results[0].ok:
            st.artifact = path
        return results[0]

    # -- 状態ごとの処理 -----------------------------------------------------
    def _do_planning(self, traj: Trajectory, st: OpsState, machine) -> None:
        """計画を実行前に検査する。落ちたらモデルを1回も呼ばない。"""
        violations = check_plan(self.plan, self.tools)
        step = self._new_step(traj, "planning", None, llm=0)
        step.thought = f"計画を実行前に検査した（違反 {len(violations)} 件）。"
        if violations:
            traj.stop_reason = "error"
            st.outcome = "handoff"
            self._escalate(st, "planning",
                           "計画が実行前の検査に通りませんでした: " + " / ".join(violations))
            self._finish_step(traj, st, machine, step, "invalid_plan")
            return
        self._finish_step(traj, st, machine, step, "plan_ready")

    def _do_preparing(self, traj: Trajectory, st: OpsState, machine) -> None:
        """読み取りだけを行う段階。副作用は1件も出さない。"""
        res = self._ask(traj, st)
        step = self._new_step(traj, "preparing", res, llm=1)
        calls, results = self._execute("preparing", st, res.calls, step)
        step.calls.extend(calls)
        step.results.extend(results)
        self._absorb(st, calls, results)

        failures = [r for r in results if not r.ok]
        if not st.missing_sources():
            self._summarize(st, step)
            self._finish_step(traj, st, machine, step, "prepared")
            return
        if failures and not all(is_actionable(r.error or "") for r in failures):
            traj.stop_reason = "error"
            st.outcome = "insufficient"
            self._escalate(st, "preparing",
                           "道具の失敗から次の行動を決められません: "
                           + " / ".join((r.error or "")[:60] for r in failures))
            self._finish_step(traj, st, machine, step, "blocked")
            return
        self._finish_step(traj, st, machine, step, "need_more")

    def _summarize(self, st: OpsState, step: Step) -> None:
        """集計を隔離環境で計算する（モデルを呼ばないので手数は増えない）。"""
        if not self.isolation:
            st.summary_available = False
            step.usage["summary"] = "skipped"
            st.notes.append("集計は付けていない（隔離実行を使わない設定）")
            return
        out = compute_summary(job=self.task_id)
        st.summary_available = bool(out["ok"])
        step.usage["summary"] = "ok" if out["ok"] else "failed"
        if out["ok"]:
            st.summary = out["stdout"]
            st.summary_ref = out["reference"]
        else:
            st.notes.append(f"集計を付けられなかった（{out['error']}）")

    def _do_requesting(self, traj: Trajectory, st: OpsState, machine) -> None:
        """次に出す副作用を決め、段階に応じて承認を依頼する。

        「もう出す操作は無い」の判定に**モデルを使わない**のが要点である
        （S11：モデルの「できました」を完了判定に使わない）。計画が終わりを知っている。
        """
        if self.confirm and st.plan_cursor >= len(self.plan):
            self._auto(traj, st, machine, "requesting", "all_done",
                       "計画のすべての操作を出し終えた。")
            return

        res = self._ask(traj, st)
        step = self._new_step(traj, "requesting", res, llm=1)
        call, offplan = self._build_call(st, res)
        if offplan:
            st.offplan.append(offplan)
            step.thought = f"{step.thought}（計画外の提案 {offplan} は採用しない）"
        if call is None:
            # 提案が無く、計画も無い（confirm=False の構成でモデルが終わりを申告した）
            self._finish_step(traj, st, machine, step, "all_done")
            return

        tool = self.tools.get(call.name)
        decision = decide(call, tool, threshold_yen=self.gate.threshold_yen)
        step.usage["mode"] = decision.mode
        step.calls.append(call)
        step.results.append(ToolResult(
            call.call_id, True,
            f"[段階の判定] {decision.mode}: {decision.reasons[-1]}"))
        st.pending = {"call_id": call.call_id, "tool": call.name, "args": dict(call.args),
                      "mode": decision.mode, "digest": call_digest(call),
                      "undo": UNDO_BY_TOOL.get(call.name, ""), "step": step.index,
                      "plan_id": self._plan_key(st, call)}

        if decision.mode in ("auto", "notify") or not self.use_gate:
            self._finish_step(traj, st, machine, step, "auto_ok")
            return

        verdict = self.gate.check(call)
        if verdict is True:
            self._finish_step(traj, st, machine, step, "auto_ok")
            return
        if verdict is False:
            reason = self.gate.reject_reason(call_digest(call)) or "理由の記録がありません"
            st.refusals.append(f"{brief_call(call)}: {reason}")
            st.pending = None
            traj.stop_reason = "error"
            self._escalate(st, "requesting", f"承認されませんでした（理由: {reason}）。")
            self._finish_step(traj, st, machine, step, "refused")
            return

        self.gate.request(call, decision)
        self._finish_step(traj, st, machine, step, "needs_approval")
        traj.stop_reason = "awaiting_approval"
        self.gate.save()
        self._save(traj, st)
        return "suspend"

    def _plan_key(self, st: OpsState, call: ToolCall) -> str:
        if self.confirm and st.plan_cursor < len(self.plan):
            return self.plan[st.plan_cursor].id
        return call.name

    def _build_call(self, st: OpsState, res) -> tuple[ToolCall | None, str]:
        """呼び出しを組み立てる。

        confirm=True … ツールと主要な引数は**計画**が決める。モデルが埋めてよいのは
                        `alterable` で宣言した引数だけ。
        confirm=False … モデルの提案をそのまま使う（比較用の危ない実装）。
        """
        proposed = res.calls[0] if res.calls else None
        if not self.confirm:
            return proposed, ""
        step = self.plan[st.plan_cursor]
        args = dict(step.args)
        offplan = ""
        if proposed is not None:
            if proposed.name != step.tool:
                offplan = f"{proposed.name}({fmt_args(proposed.args)})"[:80]
            else:
                for key in step.alterable:
                    if key in proposed.args:
                        args[key] = proposed.args[key]
        call_id = proposed.call_id if proposed is not None else f"plan-{step.id}"
        return ToolCall(call_id, step.tool, args), offplan

    def _do_waiting(self, traj: Trajectory, st: OpsState, machine):
        """承認待ち。判断が無ければ中断したまま（ステップを増やさない）。"""
        pending = st.pending or {}
        call = ToolCall(pending["call_id"], pending["tool"], dict(pending["args"]))
        digest = pending.get("digest") or call_digest(call)

        # 条件付き承認。承認者が書き換えた内容に差し替える（別の内容の承認である）
        replaced = self.gate.replacement_for(digest)
        if replaced is not None:
            call = ToolCall(call.call_id, call.name, dict(replaced))
            pending["args"] = dict(replaced)
            pending["digest"] = call_digest(call)
            st.pending = pending

        verdict = self.gate.check(call)
        if verdict is None:
            if self.gate.is_expired(digest):
                step = self._new_step(traj, "waiting", None, llm=0)
                step.thought = (f"承認期限（{self.gate.ttl_hours} 時間）を過ぎた。"
                                "勝手に実行も取り消しもせず、人に渡す。")
                step.calls.append(call)
                step.results.append(ToolResult(
                    call.call_id, False, "",
                    f"承認期限（{self.gate.ttl_hours} 時間）を過ぎたため実行しませんでした。"))
                self.gate.audit.append("expired", tool=call.name, digest=digest,
                                       mode=pending.get("mode", ""),
                                       detail=f"期限 {self.gate.expires_at(digest)} を過ぎました")
                st.pending = None
                st.outcome = "handoff"
                traj.stop_reason = "error"
                self._escalate(st, "waiting",
                               "承認期限を過ぎました。済んだ操作は残したまま人に渡します"
                               "（期限切れは却下ではないので、勝手に戻しません）。")
                self._finish_step(traj, st, machine, step, "expired")
                return None
            traj.stop_reason = "awaiting_approval"
            self._save(traj, st)
            return "suspend"

        step = self._new_step(traj, "waiting", None, llm=0)
        step.calls.append(call)
        if verdict is False:
            reason = self.gate.reject_reason(call_digest(call)) or "理由の記録がありません"
            step.thought = f"却下された（理由: {reason}）。出した副作用を戻す。"
            step.results.append(ToolResult(
                call.call_id, False, "", f"この操作は承認されませんでした（理由: {reason}）。"))
            st.refusals.append(f"{brief_call(call)}: {reason}")
            st.pending = None
            traj.stop_reason = "error"
            self._escalate(st, "waiting", f"承認されませんでした（理由: {reason}）。")
            self._finish_step(traj, st, machine, step, "rejected")
            return None

        approvers = self.gate.approvers_of(call_digest(call))
        pending["approved_by"] = list(approvers)
        st.pending = pending
        step.thought = (f"{'条件付き承認' if replaced is not None else '承認'}を確認した"
                        f"（承認者: {', '.join(approvers) or '記録なし'}）。")
        step.results.append(ToolResult(
            call.call_id, True,
            f"承認済み（照合用ハッシュ {call_digest(call)} / 承認者 {len(approvers)} 名）"))
        self._finish_step(traj, st, machine, step,
                          "amended" if replaced is not None else "approved")
        return None

    def _do_executing(self, traj: Trajectory, st: OpsState, machine) -> None:
        """承認された内容だけを実行する。"""
        pending = st.pending or {}
        step = self._new_step(traj, "executing", None, llm=0)
        call = ToolCall(pending["call_id"], pending["tool"], dict(pending["args"]))
        mode = pending.get("mode", "auto")
        step.usage["mode"] = mode

        final = self.rewrite(call) if self.rewrite else call
        if call_digest(final) != call_digest(call):
            self.gate.audit.append(
                "rewritten", tool=final.name, digest=call_digest(final), mode=mode,
                detail="実行直前に引数を組み立て直しました（承認時の内容と一致しません）")
        step.calls.append(final)

        # ① 承認と実行の同一性（S10）。ハッシュが違えば実行しない
        if self.use_gate and mode in ("approve", "dual") \
                and self.gate.check(final) is not True:
            step.thought = "承認された内容と実行しようとした内容が違う。実行しない。"
            step.results.append(ToolResult(final.call_id, False, "", MISMATCH_MESSAGE))
            self.gate.audit.append("mismatch", tool=final.name, digest=call_digest(final),
                                   mode=mode,
                                   detail="承認した内容と実行しようとした内容のハッシュが違います")
            st.pending = None
            traj.stop_reason = "error"
            self._escalate(st, "executing",
                           "承認内容と実行内容の照合用ハッシュが一致しませんでした。")
            self._finish_step(traj, st, machine, step, "failed")
            return

        # ② 冪等キーによる照合（S11）。実行の前に「もう済んでいないか」を見る
        if already_done(final.name, final.args):
            step.thought = "外部の記録に同じ冪等キーがある。二重実行を避けて次へ進む。"
            step.results.append(ToolResult(final.call_id, True, ALREADY_MESSAGE))
            self.gate.audit.append("already_done", tool=final.name,
                                   digest=call_digest(final), mode=mode,
                                   detail="外部の記録に同じ冪等キーの行があります")
            self._record_effect(st, final, mode, pending, note="照合により実行済みと判断")
            st.pending = None
            st.plan_cursor += 1
            self._finish_step(traj, st, machine, step, "advanced")
            return

        result, attempts, waited = self._call_tool(final)
        step.results.append(result)
        step.usage["tool_attempts"] = attempts
        step.usage["waited"] = waited

        if result.ok:
            step.thought = f"実行した（{brief_call(final)}）。"
            self._record_effect(st, final, mode, pending, content=result.content)
            self.gate.audit.append("notified" if mode == "notify" else "executed",
                                   tool=final.name, digest=call_digest(final), mode=mode,
                                   detail=mask_secrets(result.content[:120]))
            st.pending = None
            st.plan_cursor += 1
            self._finish_step(traj, st, machine, step, "advanced")
            return

        error = result.error or ""
        self.gate.audit.append("failed", tool=final.name, digest=call_digest(final),
                               mode=mode, detail=mask_secrets(error[:120]))
        st.pending = None

        # ③ 出力検査に引っかかった呼び出しは、その走行を止めて人に渡す
        if error.startswith("[出力検査]"):
            st.blocked_calls.append(f"{brief_call(final)}: {error[:80]}")
            step.thought = "出力検査が実行を止めた。越境の疑いがあるので人に渡す。"
            traj.stop_reason = "error"
            self._escalate(st, "executing", f"出力検査が実行を止めました（{error[:80]}）。")
            self._finish_step(traj, st, machine, step, "failed")
            return

        kind = classify_error(error)

        # ④ 部分的失敗。照合できるなら照合する。できないなら人に渡す
        if kind == PARTIAL:
            if can_match(final.name) and already_done(final.name, final.args):
                step.thought = ("実行されたか分からない失敗だが、照合したら記録があった。"
                               "再送せずに次へ進む。")
                step.results.append(ToolResult(final.call_id, True, ALREADY_MESSAGE))
                self.gate.audit.append("already_done", tool=final.name,
                                       digest=call_digest(final), mode=mode,
                                       detail="部分的失敗のあと照合で実行済みと判断")
                self._record_effect(st, final, mode, pending, note="照合により実行済みと判断")
                st.plan_cursor += 1
                self._finish_step(traj, st, machine, step, "advanced")
                return
            st.uncertain.append(brief_call(final))
            step.thought = "実行されたか分からない。照合の鍵が無いので人に渡す。"
            traj.stop_reason = "error"
            st.outcome = "handoff"
            self._escalate(st, "executing",
                           f"実行されたか分からない操作が残りました（{brief_call(final)}）。"
                           "再実行する前にデータを照合してください。")
            self._finish_step(traj, st, machine, step, "uncertain")
            return

        # ⑤ 恒久的な失敗でも、代替案が示されていれば引数を変えて出し直す
        key = pending.get("plan_id") or final.name
        if has_alternative(error) and st.alters.get(key, 0) < self.max_alter:
            st.alters[key] = st.alters.get(key, 0) + 1
            step.thought = f"同じ引数では通らない。代替案を選び直させる（{error[:60]}）。"
            self._finish_step(traj, st, machine, step, "retry_altered")
            return

        step.thought = f"回復できない失敗（{error[:60]}）。出した副作用を戻す。"
        traj.stop_reason = "error"
        self._escalate(st, "executing", f"操作が失敗しました（{error[:80]}）。")
        self._finish_step(traj, st, machine, step, "failed")

    def _call_tool(self, call: ToolCall):
        if self.retry_mode == "blind":
            return retry_blindly(self.tools, call, max_retries=self.max_retries,
                                 sleeper=self.sleeper)
        return retry_guarded(self.tools, call, max_retries=self.max_retries,
                             sleeper=self.sleeper)

    def _record_effect(self, st: OpsState, call: ToolCall, mode: str, pending: dict,
                       *, content: str = "", note: str = "") -> None:
        """出した副作用を記録する。補償はこの記録の**逆順**に行う。"""
        st.effects.append({
            "tool": call.name, "args": dict(call.args), "mode": mode,
            "digest": call_digest(call), "undo": UNDO_BY_TOOL.get(call.name, ""),
            "ref": self._reference(call, content), "note": note,
            "approved_by": list(pending.get("approved_by") or []),
            "compensated": False,
        })
        st.done_keys.append(f"{call.name}:{json.dumps(call.args, ensure_ascii=False, sort_keys=True)}")

    def _reference(self, call: ToolCall, content: str) -> str:
        if call.name == "submit_expense":
            hit = EXPENSE_ID.search(content or "")
            return hit.group(0) if hit else expense_id_by_key(
                str(call.args.get("idempotency_key") or ""))
        if call.name == "book_room":
            return f"{call.args.get('room')} {call.args.get('start')}"
        if call.name == "send_message":
            return str(call.args.get("to", ""))
        if call.name == "write_file":
            return str(call.args.get("path", ""))
        return ""

    def _do_compensating(self, traj: Trajectory, st: OpsState, machine) -> None:
        """出した副作用を逆順に打ち消す（S11）。打ち消しそのものも冪等にする。"""
        step = self._new_step(traj, "compensating", None, llm=0)
        for effect in reversed(st.effects):
            if effect.get("compensated"):
                continue
            undo = effect.get("undo") or ""
            if undo == "cancel_expense":
                message = cancel_expense_by_key(
                    str(effect["args"].get("idempotency_key") or ""))
            elif undo == "cancel_booking":
                message = cancel_booking(str(effect["args"].get("room")),
                                         str(effect["args"].get("start")))
            else:
                st.uncompensated.append(
                    f"{effect['tool']}: {effect.get('ref') or ''} は打ち消せません"
                    "（送信・持ち出しは取り消せない）")
                continue
            effect["compensated"] = True
            st.compensated.append(f"{effect['tool']}: {message}")
        if st.effects:
            st.outcome = "partial"
        elif st.outcome == "report":
            st.outcome = "handoff"
        self.gate.audit.append(
            "compensated", tool="", mode="",
            detail=f"打ち消し {len(st.compensated)} 件 / "
                   f"打ち消せなかったもの {len(st.uncompensated)} 件")
        step.thought = (f"逆順に打ち消した（成功 {len(st.compensated)} 件 / "
                        f"できなかったもの {len(st.uncompensated)} 件）。")
        self._finish_step(traj, st, machine, step,
                          "uncompensated" if st.uncompensated else "compensated")

    def _do_reporting(self, traj: Trajectory, st: OpsState, machine) -> None:
        """報告する前にデータを見る。越境が1件でもあれば報告しない。"""
        from ledger import crossings  # noqa: PLC0415

        step = self._new_step(traj, "reporting", None, llm=0)
        crossed = crossings()
        if crossed:
            step.thought = f"データ側で越境を {crossed} 件検出した。報告せずに戻す。"
            traj.stop_reason = "error"
            self._escalate(st, "reporting",
                           f"データ側で越境を {crossed} 件検出しました。"
                           "報告する前に出した副作用を戻します。")
            self._finish_step(traj, st, machine, step, "crossed")
            return
        st.outcome = "report"
        step.thought = "越境なし。実行報告を状態から組み立てて保存する。"
        result = self._write_doc("reporting", st, step, ARTIFACT_PATH, artifact_body(st))
        if not result.ok:
            traj.stop_reason = "error"
            st.outcome = "handoff"
            self._escalate(st, "reporting", f"実行報告を保存できませんでした: {result.error}")
            self._finish_step(traj, st, machine, step, "blocked")
            return
        traj.final = summary_line(st)
        self._finish_step(traj, st, machine, step, "reported")

    def _do_handoff(self, traj: Trajectory, st: OpsState, machine) -> None:
        """人へ渡す。書けても書けなくても、走行はここで終える。"""
        step = self._new_step(traj, "handoff", None, llm=0)
        if st.outcome == "report":
            st.outcome = "partial" if st.effects else "handoff"
        step.thought = "人に渡す。何が起きたか・何が残っているか・次に何をするかを1枚にする。"
        self._write_doc("handoff", st, step, HANDOFF_PATH, artifact_body(st))
        traj.final = summary_line(st)
        self._finish_step(traj, st, machine, step, "escalated")

    # -- 承認者に渡すもの ---------------------------------------------------
    def pending_call(self) -> ToolCall | None:
        pending = self.state.pending if self.state else None
        if not pending:
            return None
        return ToolCall(pending["call_id"], pending["tool"], dict(pending["args"]))

    def pending_request(self) -> str:
        call = self.pending_call()
        if call is None:
            return "承認待ちの操作はありません。"
        return self.gate.render(call, traj=self.trajectory)


def main() -> None:
    """正常系を1本だけ走らせる（承認を2回挟む）。"""
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    from agentkit.llm import ScriptedClient  # noqa: PLC0415

    from drills import LEGIT_SCRIPT  # noqa: PLC0415

    def reset() -> None:
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                       check=True, capture_output=True)

    reset()
    task_id = "TASK-M02-demo"
    tools = build_tools()[0]
    gate = ReviewGate(task_id, directory=GATE_DIR)
    gate.audit.reset()
    agent = OpsAgent(ScriptedClient(LEGIT_SCRIPT), tools, gate, task_id=task_id)
    traj = agent.run(TASK)
    print("=== 1回目：承認待ちで中断する ===")
    print(render_run(traj))
    print("\n--- 承認者に見せる情報 ---")
    print(agent.pending_request())

    rounds = 0
    while traj.stop_reason == "awaiting_approval" and rounds < 3:
        rounds += 1
        call = agent.pending_call()
        gate.approve(call, by="鈴木 彩", note="内容を確認した")
        gate.save()
        agent = OpsAgent(ScriptedClient(LEGIT_SCRIPT), tools,
                         ReviewGate.load(task_id, directory=GATE_DIR), task_id=task_id)
        traj = agent.run(TASK, resume=True)
        print(f"\n=== 承認後（{rounds} 回目）：同じ状態から再開する ===")
        print(render_run(traj))

    print("\n--- 監査ログ ---")
    print(agent.gate.audit.render())
    reset()


if __name__ == "__main__":
    main()
