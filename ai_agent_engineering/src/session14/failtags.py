#!/usr/bin/env python3
"""セッション14：失敗の分類とサンプリング — 頻度順に改善対象を選ぶ。

    python src/session14/failtags.py

障害報告は「なんかおかしい」で来る。そこから改善対象を選ぶには、1件を追えるだけでは
足りず、**同じ症状が何件あるか**を数える必要がある。ここでは軌跡から症状を決定的に
判定し、頻度順に並べる。

症状（何が見えたか）と、失敗の種類（S11 の 部分的／恒久的／一時的）は**別の軸**である。
症状は運用の入口、種類は再試行してよいかの判断に使う。混ぜると「打ち切りを再試行する」
ような対処が生まれる。

失敗の注入には S11 の `FlakyClient` をそのまま使う。`agentkit` は1行も変更しない。
"""

from __future__ import annotations

import json

from spanlog import CASES, Trajectory, reset_data, run_case  # noqa: E402

from agentkit.llm import FlakyClient, ScriptedClient  # noqa: E402
from defenses import is_internal  # noqa: E402  （S12：宛先が社内かの完全一致判定）
from failure_kinds import KIND_JA, classify_error  # noqa: E402  （S11：失敗の3分類）

S_ERROR = "例外で停止"
S_CUTOFF = "打ち切り"
S_EXTERNAL = "外部宛の送信"
S_REPEAT = "同じ操作の反復"
S_EMPTY = "空の最終回答"
S_TOOL_OK = "ツール失敗（回復済み）"
S_TOOL_NG = "ツール失敗（未回復）"

# 「警戒」で止めるもの（回復できているので失敗ではないが、数えておく）
WATCH_ONLY = (S_TOOL_OK,)
REPEAT_THRESHOLD = 3


# ---------------------------------------------------------------------------
# 症状の判定（決定的。LLM を使わない）
# ---------------------------------------------------------------------------
def failed_steps(traj: Trajectory) -> list[tuple[int, str, str]]:
    """失敗したツール結果を (ステップ番号, ツール名, エラー文) で返す。"""
    return [(step.index, call.name, result.error or "")
            for step in traj.steps
            for call, result in zip(step.calls, step.results)
            if not result.ok]


def external_sends(traj: Trajectory) -> list[tuple[int, str]]:
    """社内の宛先でない `send_message` を探す（S12 の完全一致判定を使う）。"""
    return [(step.index, str(call.args.get("to", "")))
            for step in traj.steps for call in step.calls
            if call.name == "send_message" and not is_internal(str(call.args.get("to", "")))]


def repeat_hits(traj: Trajectory, threshold: int = REPEAT_THRESHOLD) -> list[tuple[str, int]]:
    """同じ (ツール名, 引数) が閾値に達したところを返す。引数まで見るのが要点。"""
    counts: dict[tuple[str, str], int] = {}
    hits: list[tuple[str, int]] = []
    for step in traj.steps:
        for call in step.calls:
            key = (call.name, json.dumps(call.args, ensure_ascii=False, sort_keys=True))
            counts[key] = counts.get(key, 0) + 1
            if counts[key] == threshold:
                hits.append((call.name, step.index))
    return hits


def symptoms(traj: Trajectory) -> list[str]:
    """1件の軌跡から症状を並べる。1件に複数の症状が出ることがある。"""
    out: list[str] = []
    if traj.stop_reason == "error":
        out.append(S_ERROR)
    if traj.stop_reason == "max_steps":
        out.append(S_CUTOFF)
    if external_sends(traj):
        out.append(S_EXTERNAL)
    if repeat_hits(traj):
        out.append(S_REPEAT)
    if traj.stop_reason == "done" and not (traj.final or "").strip():
        out.append(S_EMPTY)
    if failed_steps(traj):
        out.append(S_TOOL_OK if traj.stop_reason == "done" else S_TOOL_NG)
    return out


def verdict(traj: Trajectory) -> str:
    """失敗 / 警戒 / 正常。**回復できた失敗を「失敗」にしない**のが要点。"""
    syms = symptoms(traj)
    if any(s not in WATCH_ONLY for s in syms):
        return "失敗"
    return "警戒" if syms else "正常"


def root_step(traj: Trajectory) -> str:
    """原因のステップ。**結果ではなく最初の異常**を指すよう優先順位をつける。"""
    syms = symptoms(traj)
    if S_EXTERNAL in syms:
        return f"step[{external_sends(traj)[0][0]}]"
    if S_REPEAT in syms:
        return f"step[{repeat_hits(traj)[0][1]}]"
    if S_ERROR in syms:
        # 例外で止まったステップは軌跡に残らない。次に来るはずだった番号を指す
        return f"step[{len(traj.steps)}]"
    if S_EMPTY in syms:
        return f"step[{len(traj.steps) - 1}]"
    if S_TOOL_OK in syms or S_TOOL_NG in syms:
        return f"step[{failed_steps(traj)[0][0]}]"
    if S_CUTOFF in syms:
        return f"step[{len(traj.steps) - 1}]"
    return "—"


def kind_of(traj: Trajectory) -> str:
    """S11 の3分類。再試行してよいかの判断に使う（症状とは別の軸）。"""
    failed = failed_steps(traj)
    if failed:
        return KIND_JA[classify_error(failed[0][2])]
    if traj.stop_reason == "error" and traj.final:
        return KIND_JA[classify_error(traj.final)]
    return "—"


# ---------------------------------------------------------------------------
# 8件の軌跡（5件は素の実行、3件は S11 の FlakyClient で失敗を注入）
# ---------------------------------------------------------------------------
FLAKY = (
    ("exception", (2,), "exception"),
    ("empty", (2,), "empty"),
    ("repeat", (2, 3), "repeat"),
)


def all_traces() -> list[Trajectory]:
    traces = [run_case(name, label, max_steps) for name, label, max_steps in CASES]
    for suffix, fail_on, mode in FLAKY:
        traces.append(run_case(
            "expense_report", "経費レポート作成", 8,
            llm=FlakyClient(ScriptedClient("expense_report"), fail_on=fail_on, mode=mode),
            task_id=f"TASK-expense_report-{suffix}"))
    return traces


def symptom_ranking(traces: list[Trajectory]) -> list[dict]:
    """症状を頻度順に並べる。同数なら**最初に見つかった順**（並びが安定する）。"""
    order: dict[str, int] = {}
    counts: dict[str, int] = {}
    example: dict[str, str] = {}
    for traj in traces:
        for s in symptoms(traj):
            if s not in order:
                order[s] = len(order)
                example[s] = traj.task_id
            counts[s] = counts.get(s, 0) + 1
    rows = [{"symptom": s, "count": counts[s], "example": example[s]} for s in counts]
    return sorted(rows, key=lambda r: (-r["count"], order[r["symptom"]]))


# ---------------------------------------------------------------------------
# サンプリング
# ---------------------------------------------------------------------------
def uniform_sample(traces: list[Trajectory], every: int = 2) -> list[Trajectory]:
    """一律サンプリング。安いが、**失敗を確実に取りこぼす**。"""
    return [t for i, t in enumerate(traces) if i % every == 0]


def tail_sample(traces: list[Trajectory], every: int = 2) -> list[Trajectory]:
    """テールベース。失敗は全件残し、それ以外だけ間引く。"""
    return [t for i, t in enumerate(traces)
            if verdict(t) == "失敗" or i % every == 0]


def sampling_rows(traces: list[Trajectory], every: int = 2) -> list[dict]:
    total = len(traces)
    failures = [t.task_id for t in traces if verdict(t) == "失敗"]
    plans = (("全件保存", traces),
             (f"一律 1/{every}（到着順）", uniform_sample(traces, every)),
             (f"テールベース（失敗は全件・それ以外 1/{every}）", tail_sample(traces, every)))
    rows = []
    for label, kept in plans:
        kept_fail = [t.task_id for t in kept if verdict(t) == "失敗"]
        rows.append({"plan": label, "kept": f"{len(kept)}/{total}",
                     "kept_failures": f"{len(kept_fail)}/{len(failures)}",
                     "lost": len(failures) - len(kept_fail)})
    return rows


def main() -> None:
    reset_data()
    traces = all_traces()

    print("=== 8件の軌跡を分類する ===")
    print("task_id | 判定 | 手数 | 停止理由 | 症状 | 原因のステップ | 失敗の種類（S11）")
    for traj in traces:
        print(" | ".join([traj.task_id, verdict(traj), str(len(traj.steps)), traj.stop_reason,
                          "／".join(symptoms(traj)) or "—", root_step(traj), kind_of(traj)]))

    print("\n=== 症状の頻度（改善対象を頻度順に選ぶ）===")
    print("症状 | 件数 | 代表 task_id")
    for row in symptom_ranking(traces):
        print(f"{row['symptom']} | {row['count']} | {row['example']}")
    print("→ 1件を追えるようになったら、次は同じ症状を数える。"
          "頻度が同じなら、被害の大きい症状（外部宛の送信）から直す。")

    print("\n=== サンプリング（全部は残せない）===")
    print("方式 | 保存 | 失敗の保存 | 取りこぼした失敗")
    for row in sampling_rows(traces):
        print(f"{row['plan']} | {row['kept']} | {row['kept_failures']} | {row['lost']}")
    print("→ 一律に間引くと失敗から先に消える。失敗は全件・正常だけ間引くと決めれば、"
          "保存量を減らしても診断能力は落ちない。")

    reset_data()


if __name__ == "__main__":
    main()
