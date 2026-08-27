#!/usr/bin/env python3
"""セッション3の演習の完成版：ReAct ループを自分で書く。

`agentkit.loop.ReActAgent` と同じことを、演習として一から書き直した実装。
既定の `ReActAgent` との違いは1つだけ——**上限に達したときの振る舞いを選べる**。

  on_limit="fail"    … 失敗として返す（final は None のまま）
  on_limit="partial" … 途中結果を返す
  on_limit="handoff" … 人間への引き継ぎメモを返す

どの振る舞いでも `stop_reason` を `done` にしないことが要点。
「上限に達したのに成功として返す」がエージェントで最も多い事故だからである。
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.clock import FixedClock  # noqa: E402
from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: E402

ON_LIMIT_CHOICES = ("fail", "partial", "handoff")

# ---------------------------------------------------------------------------
# シナリオはファイル（scenarios/*.json）でなく dict でも渡せる。
# 章の中だけで使う小さなシナリオは、こうしてコードの近くに置くと読みやすい。
# ---------------------------------------------------------------------------
ONE_STEP = {
    "name": "one_step",
    "turns": [
        {"thought": "条文はすでに分かっているので、ツールを使わずそのまま答える。",
         "final": "1件5万円以上の経費は事前承認が必要です。"},
    ],
}

PARALLEL_READS = {
    "name": "parallel_reads",
    "turns": [
        {"thought": "互いに独立した3つの読み取りをまとめて依頼する。",
         "calls": [
             {"name": "get_policy", "args": {"topic": "経費精算"}},
             {"name": "list_expenses", "args": {"status": "all"}},
             {"name": "search_docs", "args": {"query": "会議室", "limit": 2}},
         ]},
        {"thought": "材料がそろったので報告する。",
         "final": "規程・申請一覧・関連文書の3点を取得しました。"},
    ],
}

MIXED_CALLS = {
    "name": "mixed_calls",
    "turns": [
        {"thought": "一覧の取得と下書きの保存を一度に頼んでしまう。",
         "calls": [
             {"name": "list_expenses", "args": {"status": "submitted"}},
             {"name": "write_file", "args": {"path": "draft.md", "content": "# 下書き\n"}},
         ]},
        {"thought": "保存できたので報告する。",
         "final": "draft.md に下書きを保存しました。"},
    ],
}


class MyReActAgent:
    """観測 → 思考 → 行動 を繰り返す最小のエージェント（演習版）。"""

    def __init__(self, llm, tools, *, max_steps: int = 8, budget=None,
                 clock=None, on_limit: str = "fail", parallel: bool = False,
                 system: str = "") -> None:
        if on_limit not in ON_LIMIT_CHOICES:
            raise ValueError(f"on_limit は {ON_LIMIT_CHOICES} のいずれかです: {on_limit!r}")
        if max_steps < 1:
            raise ValueError("max_steps は1以上で指定してください。")
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.budget = budget
        self.clock = clock or FixedClock()
        self.on_limit = on_limit
        self.parallel = parallel
        self.system = system

    # -- ループ本体 ---------------------------------------------------------
    def run(self, task: str, task_id: str = "TASK-001") -> Trajectory:
        traj = Trajectory(task_id=task_id, task=task)
        specs = self.tools.specs()

        while True:
            # ① 停止条件は「行動する前」に見る（超えてから止めるのでは遅い）
            if len(traj.steps) >= self.max_steps:
                return self._stop_at_limit(traj, "max_steps")
            if self.budget is not None and self.budget.exceeded(traj):
                return self._stop_at_limit(traj, "budget")

            # ② 観測：会話履歴は保持せず、軌跡から毎回組み立て直す
            messages = self.build_messages(task, traj)

            # ③ 思考：次の一手を LLM に尋ねる
            try:
                res = self.llm.respond(messages, specs)
            except Exception as exc:  # noqa: BLE001
                # 呼び出しが壊れたら error で終わる（再試行はセッション11で足す）
                traj.stop_reason = "error"
                traj.final = f"LLM 呼び出しに失敗しました: {type(exc).__name__}: {exc}"
                return traj

            step = Step(index=len(traj.steps), thought=res.thought,
                        usage={"input_tokens": res.input_tokens,
                               "output_tokens": res.output_tokens})

            # ④ 完了判定：ツールを呼ばない応答＝最終回答
            if not res.calls:
                traj.steps.append(step)
                traj.final = res.final if res.final is not None else res.thought
                traj.stop_reason = "done"
                return traj

            # ⑤ 行動：ツールを呼び、成功も失敗もそのまま軌跡に残す
            step.calls.extend(res.calls)
            mode, results = self._invoke(res.calls)
            step.results.extend(results)
            step.usage["batch"] = mode
            traj.steps.append(step)

    # -- 会話履歴の組み立て -------------------------------------------------
    def build_messages(self, task: str, traj: Trajectory) -> list[dict]:
        """軌跡から会話履歴（LLM に渡すメッセージ列）を作る。

        `tool_use` の `id` と `tool_result` の `tool_use_id` を必ず対応させる。
        ここがずれると「どの依頼に対する結果か」が分からなくなる。
        """
        messages: list[dict] = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        messages.append({"role": "user", "content": task})
        for s in traj.steps:
            if not s.calls:
                continue  # 最終回答のステップは履歴に足さない（次の一手が無い）
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

    # -- ツールの呼び出し（直列 / 並列） ------------------------------------
    def _invoke(self, calls: list[ToolCall]) -> tuple[str, list[ToolResult]]:
        """並列にしてよいと判断できるときだけ並列にする。

        `map` は入力の順序どおりに結果を返すので、並列でも軌跡は決定的になる。
        """
        if self.parallel and len(calls) > 1 and all(self._parallel_safe(c) for c in calls):
            with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                return "parallel", list(pool.map(self.tools.call, calls))
        return "serial", [self.tools.call(c) for c in calls]

    def _parallel_safe(self, call: ToolCall) -> bool:
        """読み取り専用のツールだけを並列の対象にする。"""
        tool = self.tools.get(call.name)
        return tool is not None and "read" in tool.tags

    # -- 上限に達したときの振る舞い -----------------------------------------
    def _stop_at_limit(self, traj: Trajectory, reason: str) -> Trajectory:
        traj.stop_reason = reason  # done にはしない。ここが事故の分かれ目
        if self.on_limit == "fail":
            traj.final = None
        elif self.on_limit == "partial":
            traj.final = self._partial_report(traj)
        else:
            traj.final = self._handoff_note(traj)
        return traj

    def _partial_report(self, traj: Trajectory) -> str:
        """途中結果を、未完了だと分かる形でまとめる。"""
        lines = [f"【未完了】{self.max_steps} ステップの上限に達したため中断しました。",
                 "ここまでに確認できたこと:"]
        for step in traj.steps:
            for call, result in zip(step.calls, step.results):
                text = result.content if result.ok else (result.error or "")
                head = text.splitlines()[0] if text.splitlines() else ""
                lines.append(f"- step {step.index} {call.name}: "
                             f"{'成功' if result.ok else '失敗'} / {head[:40]}")
        lines.append("この内容は途中結果です。続きは人間が確認してください。")
        return "\n".join(lines)

    def _handoff_note(self, traj: Trajectory) -> str:
        """人間が次の判断をするために必要な情報だけを並べる。"""
        last_thought = traj.steps[-1].thought if traj.steps else "（思考なし）"
        return "\n".join([
            "【要対応】上限に達したため人間に引き継ぎます。",
            f"タスク: {traj.task}",
            f"手数: {len(traj.steps)} / 上限: {self.max_steps}",
            f"呼んだツール: {', '.join(traj.tool_names) or 'なし'}",
            f"最後に考えていたこと: {last_thought}",
            "次にやること: 上限が妥当か確認し、必要なら上限を上げて再実行してください。",
        ])


# ---------------------------------------------------------------------------
# 軌跡の表示と要約
# ---------------------------------------------------------------------------
def render_trace(traj: Trajectory, *, show_final: bool = True) -> str:
    """軌跡を1行1ステップで読める形にする。"""
    lines = [f"task_id={traj.task_id} stop_reason={traj.stop_reason} 手数={len(traj.steps)}"]
    for step in traj.steps:
        names = ", ".join(c.name for c in step.calls) or "（最終回答）"
        mode = step.usage.get("batch")
        suffix = f"  [{mode}]" if mode else ""
        lines.append(f"  step {step.index}: {names}{suffix}")
        for call, result in zip(step.calls, step.results):
            if result.ok:
                lines.append(f"      ok {call.name}")
            else:
                lines.append(f"      NG {call.name}: {(result.error or '').splitlines()[0]}")
    if show_final:
        lines.append(f"  final: {traj.final}")
    return "\n".join(lines)


def summarize_jsonl(path: str | Path) -> dict:
    """保存した軌跡（1行1ステップの JSONL）を読み、内訳を返す。"""
    traj = Trajectory.from_jsonl(path)
    total = traj.total_tokens
    return {
        "task_id": traj.task_id,
        "steps": len(traj.steps),
        "tool_calls": len(traj.tool_names),
        "tools": traj.tool_names,
        "input_tokens": total["input"],
        "output_tokens": total["output"],
        "stop_reason": traj.stop_reason,
        "completed": traj.stop_reason == "done",
    }


# ---------------------------------------------------------------------------
# 上限の決め方と、上限に達したときの振る舞いの選び方
# ---------------------------------------------------------------------------
def recommend_max_steps(depth: int, *, retry_margin: int = 2, report_step: int = 1) -> int:
    """タスクの深さから `max_steps` を決める。

    depth        … 正常に進んだときに必要なツール呼び出しの回数（設計時の見積り）
    retry_margin … 失敗して言い直すための余裕（既定2手）
    report_step  … 最後に「終わりました」と答えるための1手
    """
    if depth < 1:
        raise ValueError("depth は1以上で指定してください。")
    if retry_margin < 0 or report_step < 0:
        raise ValueError("retry_margin と report_step は0以上で指定してください。")
    return depth + retry_margin + report_step


def choose_on_limit(*, has_side_effect: bool, partial_is_useful: bool,
                    retry_is_cheap: bool) -> str:
    """上限に達したときの振る舞いを決める。"""
    if has_side_effect:
        # 途中まで書き換えた状態を機械が勝手に判断してはいけない
        return "handoff"
    if partial_is_useful:
        # 調査・集計は途中結果でも価値がある
        return "partial"
    if retry_is_cheap:
        # 読み取りだけで、やり直しが安いなら黙って失敗でよい
        return "fail"
    return "handoff"
