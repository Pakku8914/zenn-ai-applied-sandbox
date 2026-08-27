#!/usr/bin/env python3
"""セッション10：承認ゲートを挟んで走り、承認後に同じ状態から再開する実行器。

`agentkit` は1行も変更していない。使うのは次の3つだけである。

  - `agentkit.models.Trajectory.stop_reason` … `awaiting_approval` を最初から持っている
  - `agentkit.approval.ApprovalGate` … 決定の記録とハッシュ（`gate.py` で拡張）
  - `agentkit.state.Checkpoint` … 中断中の置き場（セッション6と同じもの）

セッション3の `ReActAgent` は `awaiting_approval` で**止まる**ことはできるが、
承認後に**保留した操作を実行して続ける**ことができない（`gap.py` で実演する）。
足りないのは次の3点で、この層で足す。

  1. 保留した呼び出しを軌跡の中に置き、承認後はモデルに聞き直さずに実行する
  2. 実行する内容が承認された内容と同じであることをハッシュで確かめる
  3. 却下・条件付き承認・期限切れ・二度押しを、それぞれ別の振る舞いにする
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.approval import call_digest  # noqa: E402
from agentkit.biztools import DATA  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402
from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: E402
from agentkit.state import Checkpoint  # noqa: E402
from policy import decide, escalate  # noqa: E402

DEFAULT_DIR = ROOT / "traces" / "checkpoints" / "session10"


# ---------------------------------------------------------------------------
# 中断中に持ち越す状態。セッション6の `TaskState` と同じ名前の欄を使う
#   pending   … 人間の判断を待っている操作（S06 では「保存前に落ちた操作」だった）
#   done_keys … 実行し終えた副作用の目印（二度押しを弾くのに使う）
#   llm_calls … これまでにモデルに聞いた回数（再開位置の同期用）
# ---------------------------------------------------------------------------
@dataclass
class RunState:
    task_id: str
    pending: dict | None = None
    done_keys: list = field(default_factory=list)
    llm_calls: int = 0

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "pending": self.pending,
                "done_keys": list(self.done_keys), "llm_calls": self.llm_calls}

    @classmethod
    def from_dict(cls, data: dict) -> "RunState":
        return cls(task_id=data["task_id"], pending=data.get("pending"),
                   done_keys=list(data.get("done_keys", [])),
                   llm_calls=int(data.get("llm_calls", 0)))


def build_messages(task: str, traj: Trajectory) -> list[dict]:
    """会話履歴を軌跡から組み立て直す（セッション3と同じ形）。"""
    messages: list[dict] = [{"role": "user", "content": task}]
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


def llm_calls(traj: Trajectory) -> int:
    """手数（＝LLM を呼んだ回数）。承認を挟んでも増えないことを確かめるのに使う。"""
    return sum(1 for s in traj.steps if s.usage.get("llm", 1))


def effect_key(call: ToolCall) -> str:
    """副作用の目印。同じ操作を2回実行していないかを見るのに使う。"""
    return f"{call.name}:{json.dumps(call.args, ensure_ascii=False, sort_keys=True)}"


def render_run(traj: Trajectory) -> str:
    """1行1ステップで「どの段階で何をして、どう決着したか」を表示する。"""
    lines = [f"task_id={traj.task_id} stop_reason={traj.stop_reason} "
             f"手数={llm_calls(traj)}"]
    for step in traj.steps:
        if step.calls:
            marks = []
            for index, call in enumerate(step.calls):
                if index < len(step.results):
                    marks.append(f"{call.name}:{'ok' if step.results[index].ok else 'NG'}")
                else:
                    marks.append(f"{call.name}:待ち")
            action = " ".join(marks)
        else:
            action = "（ツールなし）"
        mode = step.usage.get("mode", "")
        suffix = f" [{mode}]" if mode else ""
        state = step.usage.get("state", "?")
        event = step.usage.get("event") or "（決着なし）"
        lines.append(f"  step {step.index} <{state}> {action}{suffix} -> {event}")
    lines.append(f"  final: {traj.final}")
    return "\n".join(lines)


def inflate_amount(call: ToolCall) -> ToolCall:
    """バグ入りの書き換え（演習用）。

    「実行直前に最新の金額をデータから引き直す」つもりで、別の申請の金額を
    拾ってしまう実装。承認した内容と実行する内容がずれる典型である。
    冪等キーは古いままなので、データ側でも金額とキーが食い違う。
    """
    if call.name != "submit_expense":
        return call
    return ToolCall(call.call_id, call.name, {**call.args, "amount": 148_000})


# ---------------------------------------------------------------------------
class ApprovalRunner:
    """承認ゲートを挟んだ実行器。

    on_reject … "alternative"（却下理由をモデルに返して続ける）/ "abort"（中止する）
    rewrite   … 実行直前に引数を組み立て直す関数（既定は何もしない）
    """

    def __init__(self, llm, tools, gate, *, task_id: str = "TASK-010",
                 max_steps: int = 8, clock=None, checkpoint_dir: Path | None = None,
                 on_reject: str = "alternative", rewrite=None) -> None:
        if on_reject not in ("alternative", "abort"):
            raise ValueError(f"on_reject は alternative か abort です: {on_reject!r}")
        self.llm = llm
        self.tools = tools
        self.specs = tools.specs()
        self.gate = gate
        self.task_id = task_id
        self.max_steps = max_steps
        self.clock = clock or FixedClock()
        self.dir = Path(checkpoint_dir) if checkpoint_dir else DEFAULT_DIR
        self.on_reject = on_reject
        self.rewrite = rewrite
        self.state: RunState | None = None
        self.trajectory: Trajectory | None = None

    # -- 走行 ---------------------------------------------------------------
    def run(self, task: str, *, resume: bool = False) -> Trajectory:
        if resume:
            checkpoint = Checkpoint.load(self.task_id, self.dir)
            traj = checkpoint.trajectory
            st = RunState.from_dict(checkpoint.state)
            self.state, self.trajectory = st, traj
            if traj.stop_reason in ("done", "error"):
                # 終わっている走行は再開しない（承認画面を二度開いても副作用を出さない）
                return traj
            self._sync_oracle(st.llm_calls)
            if st.pending is not None:
                outcome = self._settle_pending(traj, st)
                if outcome == "awaiting":
                    traj.stop_reason = "awaiting_approval"
                    return traj
                if outcome == "aborted":
                    return traj
        else:
            traj = Trajectory(task_id=self.task_id, task=task)
            st = RunState(task_id=self.task_id)
            self.state, self.trajectory = st, traj

        while True:
            # 打ち切りは行動の前に判定する（セッション3と同じ順序）
            if len(traj.steps) >= self.max_steps:
                traj.stop_reason = "max_steps"
                self._save(traj, st)
                return traj

            try:
                res = self.llm.respond(build_messages(task, traj), self.specs)
            except Exception as exc:  # noqa: BLE001
                traj.stop_reason = "error"
                traj.final = f"LLM 呼び出しに失敗しました: {type(exc).__name__}: {exc}"
                self._save(traj, st)
                return traj
            st.llm_calls += 1

            step = Step(index=len(traj.steps), thought=res.thought,
                        usage={"input_tokens": res.input_tokens,
                               "output_tokens": res.output_tokens, "llm": 1,
                               "state": "running", "event": "", "mode": ""})

            if not res.calls:
                step.usage["event"] = "done"
                traj.steps.append(step)
                traj.final = res.final if res.final is not None else res.thought
                traj.stop_reason = "done"
                self._save(traj, st)
                return traj

            for call in res.calls:
                step.calls.append(call)
                decision = decide(call, self.tools.get(call.name),
                                  threshold_yen=self.gate.threshold_yen)
                step.usage["mode"] = escalate(step.usage["mode"] or "auto", decision.mode)

                if decision.mode in ("auto", "notify"):
                    step.usage["event"] = self._perform(call, step, st, decision.mode)
                    continue

                verdict = self.gate.check(call)
                if verdict is True:  # すでに承認が揃っている
                    step.usage["event"] = self._perform(call, step, st, decision.mode)
                    continue
                if verdict is False:  # すでに却下されている
                    step.usage["event"] = self._refuse(call, step, st)
                    if self.on_reject == "abort":
                        traj.steps.append(step)
                        traj.stop_reason = "error"
                        traj.final = ("承認されなかったため中止しました。理由: "
                                      + self.gate.reject_reason(call_digest(call)))
                        self._save(traj, st)
                        return traj
                    continue

                # 未判断 → 依頼を出して中断する。同じステップの続きは実行しない
                request = self.gate.request(call, decision)
                st.pending = {"call_id": call.call_id, "tool": call.name,
                              "args": dict(call.args), "digest": request["digest"],
                              "mode": decision.mode, "step": step.index}
                step.usage["state"] = "awaiting_approval"
                step.usage["event"] = "awaiting"
                traj.steps.append(step)
                traj.stop_reason = "awaiting_approval"
                self._save(traj, st)
                self.gate.save()
                return traj

            traj.steps.append(step)
            self._save(traj, st)

    # -- 承認待ちの決着 -----------------------------------------------------
    def _settle_pending(self, traj: Trajectory, st: RunState) -> str:
        """保留していた操作の始末をする。戻り値は awaiting / continued / aborted。

        ここでモデルに聞き直さないのが要点である。聞き直すと、承認した内容と
        違う内容が返ってくる余地が生まれる（`inflate_amount` で実演する）。
        """
        pending = st.pending or {}
        index = int(pending.get("step", len(traj.steps) - 1))
        step = traj.steps[min(index, len(traj.steps) - 1)]
        call = ToolCall(pending["call_id"], pending["tool"], dict(pending["args"]))
        approved_digest = pending["digest"]

        # ① 条件付き承認。承認者が書き換えた内容に差し替える
        replaced = self.gate.replacement_for(approved_digest)
        if replaced is not None:
            call = ToolCall(call.call_id, call.name, replaced)

        verdict = self.gate.check(call)

        # ② まだ判断が無い。期限を過ぎていたら諦める
        if verdict is None:
            if self.gate.is_expired(approved_digest):
                st.pending = None
                self.gate.audit.append(
                    "expired", tool=call.name, digest=approved_digest,
                    mode=pending.get("mode", ""),
                    detail=f"期限 {self.gate.expires_at(approved_digest)} を過ぎました")
                step.results.append(ToolResult(
                    call.call_id, False, "",
                    f"承認期限（{self.gate.ttl_hours} 時間）を過ぎたため実行しませんでした。"
                    "改めて承認を依頼するか、別の方法を検討してください。"))
                step.usage["state"] = "resumed"
                step.usage["event"] = "expired"
                self._save(traj, st)
                return "continued"
            return "awaiting"

        # ③ 却下
        if verdict is False:
            st.pending = None
            step.usage["event"] = self._refuse(call, step, st)
            step.usage["state"] = "resumed"
            if self.on_reject == "abort":
                traj.stop_reason = "error"
                traj.final = ("承認されなかったため中止しました。理由: "
                              + self.gate.reject_reason(call_digest(call)))
                self._save(traj, st)
                return "aborted"
            self._save(traj, st)
            return "continued"

        # ④ 承認済み。実行する
        st.pending = None
        step.usage["state"] = "resumed"
        step.usage["event"] = self._perform(call, step, st, pending.get("mode", "approve"))
        step.usage["approved_by"] = self.gate.approvers_of(call_digest(call))
        self._save(traj, st)
        return "continued"

    # -- 実行と拒否 ---------------------------------------------------------
    def _perform(self, call: ToolCall, step: Step, st: RunState, mode: str) -> str:
        """承認済み（または承認の要らない）呼び出しを実行する。戻り値はイベント名。"""
        final = self.rewrite(call) if self.rewrite else call

        # 実行直前に引数が変わったら、それは「承認した内容と違うもの」である
        if call_digest(final) != call_digest(call):
            self.gate.audit.append(
                "rewritten", tool=call.name, digest=call_digest(final), mode=mode,
                detail="実行直前に引数を組み立て直しました（承認時の内容と一致しません）")

        if mode in ("approve", "dual") and self.gate.check(final) is not True:
            step.results.append(ToolResult(
                call.call_id, False, "",
                "承認内容と実行内容が一致しません（照合用ハッシュが違います）。実行しませんでした。"
                "承認された内容で実行し直すか、改めて承認を依頼してください。"))
            self.gate.audit.append(
                "mismatch", tool=call.name, digest=call_digest(final), mode=mode,
                detail="承認した内容と実行しようとした内容のハッシュが違います")
            return "mismatch"

        if self._already_done(final):
            step.results.append(ToolResult(
                call.call_id, True,
                "既に実行済みでした（同じ冪等キーの記録があります）。二重実行を避けました。"))
            self.gate.audit.append(
                "already_done", tool=call.name, digest=call_digest(final), mode=mode,
                detail="外部の記録に同じ冪等キーの行があります")
            return "already_done"

        result = self.tools.call(final)
        step.results.append(result)
        tool = self.tools.get(final.name)
        if result.ok and tool is not None and not tool.idempotent:
            st.done_keys.append(effect_key(final))
        if mode != "auto":  # 読み取りや作業領域の操作は軌跡に残る。監査ログには書かない
            if not result.ok:
                event = "failed"
            else:
                event = "notified" if mode == "notify" else "executed"
            self.gate.audit.append(
                event, tool=final.name, digest=call_digest(final), mode=mode,
                detail=(result.content if result.ok else (result.error or "")))
        return "executed" if result.ok else "failed"

    def _refuse(self, call: ToolCall, step: Step, st: RunState) -> str:
        reason = self.gate.reject_reason(call_digest(call)) or "理由の記録がありません"
        tail = "" if self.on_reject == "abort" else "別の方法を検討してください。"
        step.results.append(ToolResult(
            call.call_id, False, "",
            f"この操作は承認されませんでした（理由: {reason}）。{tail}"))
        return "rejected"

    def _already_done(self, call: ToolCall) -> bool:
        """外部の記録を見て、その操作が済んでいるかを確かめる（セッション6と同じ考え方）。

        照合の鍵はセッション4の**冪等キー**である。承認のハッシュは保存されていないので
        照合には使えない。2つの鍵は目的が違う。
        """
        if effect_key(call) in (self.state.done_keys if self.state else []):
            return True
        if call.name != "submit_expense":
            return False
        key = call.args.get("idempotency_key")
        if not key:
            return False
        path = DATA / "expenses.jsonl"
        if not path.exists():
            return False
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            if json.loads(line).get("idempotency_key") == key:
                return True
        return False

    # -- 保存と再開 ---------------------------------------------------------
    def _save(self, traj: Trajectory, st: RunState) -> None:
        Checkpoint(task_id=self.task_id, trajectory=traj, state=st.to_dict()).save(self.dir)

    def _sync_oracle(self, position: int) -> None:
        """再開時にオラクルの位置を「これまでに聞いた回数」に合わせる（セッション6と同じ）。"""
        if hasattr(self.llm, "cursor"):
            self.llm.cursor = position

    # -- 承認者に渡すもの ---------------------------------------------------
    def pending_call(self) -> ToolCall | None:
        """いま承認を待っている呼び出し。承認画面はこれを表示する。"""
        pending = self.state.pending if self.state else None
        if not pending:
            return None
        return ToolCall(pending["call_id"], pending["tool"], dict(pending["args"]))

    def pending_request(self) -> str:
        call = self.pending_call()
        if call is None:
            return "承認待ちの操作はありません。"
        return self.gate.render(call, traj=self.trajectory)


if __name__ == "__main__":
    import subprocess

    from agentkit.biztools import build_registry
    from agentkit.llm import ScriptedClient
    from approval_scenarios import TASK, EXPENSE_APPROVAL
    from gate import ReviewGate

    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)
    gate = ReviewGate("TASK-010")
    gate.audit.reset()
    runner = ApprovalRunner(ScriptedClient(EXPENSE_APPROVAL), build_registry(), gate,
                            task_id="TASK-010")
    print("=== 1回目：承認待ちで中断する ===")
    print(render_run(runner.run(TASK)))
    print("\n--- 承認者に見せる情報 ---")
    print(runner.pending_request())

    call = runner.pending_call()
    gate.approve(call, by="鈴木 彩", note="内容を確認。参加者名簿は後追いで提出させる")
    gate.save()

    print("\n=== 承認後：同じ状態から再開する ===")
    resumed = ApprovalRunner(ScriptedClient(EXPENSE_APPROVAL), build_registry(),
                             ReviewGate.load("TASK-010"), task_id="TASK-010")
    print(render_run(resumed.run(TASK, resume=True)))
    print("\n--- 監査ログ ---")
    print(resumed.gate.audit.render())
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)
