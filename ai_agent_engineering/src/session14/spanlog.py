#!/usr/bin/env python3
"""セッション14：スパンの記録 — 1件のタスクを後から追える形にする。

    python src/session14/spanlog.py

`agentkit.trace.Tracer` は最小実装である（スパンを集めるだけ）。実運用で1件を追う
には足りないものが4つある。

  1. task スパンが無い（1件の全体像が始点を持たない）
  2. 親子関係が残らない（`depth` はあるが親の ID が無い）
  3. `call_id` が入らない（同じツールを6回呼ぶと、どの呼び出しか分からない）
  4. 所要が実時間（`time.perf_counter()`）なので、同じ入力でも値が変わる

本モジュールは `agentkit` を1行も変更せず、**軌跡（Trajectory）からスパンの木を作る**。
軌跡には `call_id`・ツール結果・`usage` がすべて残っているので、後から投影できる。
所要は「回数 × 単価」で出す。単価は宣言値であり、実測のレイテンシではない。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# S11（失敗の分類）と S12（機密のマスキング）の実装をそのまま使う。
# 既存ファイルは1行も変更せず、import 経路だけを足す（復習03 と同じ作法）。
_DIRS = (ROOT, HERE, ROOT / "tools", ROOT / "src" / "session11", ROOT / "src" / "session12")
for _d in _DIRS:
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402
from agentkit.trace import Tracer  # noqa: E402

TRACE_DIR = ROOT / "traces" / "session14"
KINDS = ("task", "step", "llm", "tool")


# ---------------------------------------------------------------------------
# 単価表（所要の出し方）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LatencyUnits:
    """所要の単価表。**実測のレイテンシではなく、こちらが宣言する固定値**である。

    実時間を測るとトレースが再現しなくなる（同じ入力でも毎回違う値になる）。
    本書は「回数 × 単価」で決定的に出し、単価表そのものを記録に含める。
    単価は各自の環境で計測して差し替える前提の値である。

    `run_python` だけは実測値を入れてある：隔離実行の往復は 115 ms
    （2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13）。
    """

    label: str
    llm_ms: int
    tool_ms: int
    per_tool: dict = field(default_factory=dict)

    def cost(self, kind: str, name: str) -> int:
        if kind == "llm":
            return self.llm_ms
        if kind == "tool":
            return int(self.per_tool.get(name, self.tool_ms))
        return 0

    def describe(self) -> str:
        return (f"{self.label}（llm={self.llm_ms}ms / tool={self.tool_ms}ms / "
                f"run_python={self.per_tool.get('run_python', self.tool_ms)}ms は 2026-08-15 実測）")


UNITS_A = LatencyUnits("単価表 A: LLM が支配的", llm_ms=500, tool_ms=20,
                       per_tool={"run_python": 115})
UNITS_B = LatencyUnits("単価表 B: ツールが支配的", llm_ms=50, tool_ms=300,
                       per_tool={"run_python": 115})


# ---------------------------------------------------------------------------
# スパン
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SpanRecord:
    """1区間の記録。相関IDは **どの粒度でも必ず残す**（削るのは中身だけ）。"""

    span_id: str
    parent_id: str | None
    task_id: str
    kind: str          # task / step / llm / tool
    name: str
    depth: int
    ms: int
    attrs: dict = field(default_factory=dict)


def spans_from_trajectory(traj: Trajectory, units: LatencyUnits = UNITS_A) -> list[SpanRecord]:
    """軌跡からスパンの木を作る（task → step → llm / tool の3階層）。

    スパン ID は `{task_id}/{通し番号}`。**行き掛け順**（親が先）で採番するので、
    ファイルを上から読むだけで木が復元できる。
    """
    seq = 0

    def new_id() -> str:
        nonlocal seq
        sid = f"{traj.task_id}/{seq:02d}"
        seq += 1
        return sid

    out: list[SpanRecord] = []
    task_span_id = new_id()
    out.append(SpanRecord(task_span_id, None, traj.task_id, "task", traj.task or traj.task_id,
                          0, 0, {"stop_reason": traj.stop_reason, "steps": len(traj.steps)}))

    total = 0
    for step in traj.steps:
        step_slot = len(out)
        step_span_id = new_id()
        out.append(SpanRecord(step_span_id, task_span_id, traj.task_id, "step",
                              f"step[{step.index}]", 1, 0, {"index": step.index}))

        llm_ms = units.cost("llm", "llm")
        out.append(SpanRecord(new_id(), step_span_id, traj.task_id, "llm",
                              f"llm[{step.index}]", 2, llm_ms,
                              {"index": step.index,
                               "in": step.usage.get("input_tokens", 0),
                               "out": step.usage.get("output_tokens", 0),
                               "thought": step.thought}))
        step_ms = llm_ms

        results = {r.call_id: r for r in step.results}
        for call in step.calls:
            res = results.get(call.call_id)
            text = "" if res is None else (res.content if res.ok else (res.error or ""))
            tool_ms = units.cost("tool", call.name)
            step_ms += tool_ms
            out.append(SpanRecord(new_id(), step_span_id, traj.task_id, "tool", call.name, 2,
                                  tool_ms,
                                  {"call_id": call.call_id,
                                   "ok": None if res is None else bool(res.ok),
                                   "step": step.index,
                                   "args": dict(call.args),
                                   "result": text,
                                   "result_len": len(text)}))

        out[step_slot] = replace(out[step_slot], ms=step_ms)
        total += step_ms

    out[0] = replace(out[0], ms=total)
    return out


def counts_by_kind(spans: list[SpanRecord]) -> dict[str, int]:
    return {kind: sum(1 for s in spans if s.kind == kind) for kind in KINDS}


def census(spans: list[SpanRecord]) -> str:
    c = counts_by_kind(spans)
    return (f"スパン数={len(spans)}（task={c['task']} step={c['step']} "
            f"llm={c['llm']} tool={c['tool']}）")


def find_by_call_id(spans: list[SpanRecord], call_id: str) -> list[SpanRecord]:
    """相関ID からスパンを引く。**一意に決まること**が追跡の前提になる。"""
    return [s for s in spans if s.attrs.get("call_id") == call_id]


def ancestors(spans: list[SpanRecord], span_id: str) -> list[str]:
    """親をたどって根まで並べる。1件の中の位置がこれで決まる。"""
    index = {s.span_id: s for s in spans}
    path = [span_id]
    current = index[span_id].parent_id
    while current is not None:
        path.append(current)
        current = index[current].parent_id
    return path


def render_tree(spans: list[SpanRecord]) -> list[str]:
    lines = []
    for s in spans:
        extra = ""
        if s.kind == "tool":
            extra = f"  call_id={s.attrs['call_id']}  ok={s.attrs['ok']}"
        lines.append(f"{'  ' * s.depth}{s.kind:<5} {s.span_id}  {s.name}  {s.ms}ms{extra}")
    return lines


def save_spans(spans: list[SpanRecord], path: Path) -> Path:
    """スパンを JSONL に落とす。

    **この関数は全文（無加工）で書き出す。** 実際に残すときは、保存の直前に
    `redaction.record_for()` で粒度を選ぶこと（機密がそのまま長期保存されるため）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in spans:
            f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
    return path


def load_spans(path: Path) -> list[SpanRecord]:
    return [SpanRecord(**json.loads(line))
            for line in path.open(encoding="utf-8") if line.strip()]


# ---------------------------------------------------------------------------
# 走らせる（決定的。何度実行しても同じ軌跡になる）
# ---------------------------------------------------------------------------
CASES: tuple[tuple[str, str, int], ...] = (
    ("expense_report", "経費レポート作成", 8),
    ("book_room_conflict", "会議室予約（競合あり）", 8),
    ("submit_expense_approval", "経費申請（5万円以上）", 8),
    ("injection_naive", "社外連絡の雛形を調べて共有", 8),
    ("max_steps_loop", "同じ検索を繰り返す", 6),
)

_make_data = None


def reset_data() -> None:
    """業務データを初期状態に戻す（S12・S13 と同じ作法）。"""
    global _make_data
    if _make_data is None:
        import make_data  # noqa: PLC0415

        _make_data = make_data
    with contextlib.redirect_stdout(io.StringIO()):
        _make_data.main()


def run_case(scenario: str, label: str, max_steps: int = 8, *,
             llm=None, tools=None, task_id: str | None = None) -> Trajectory:
    """1ケースを走らせる。`llm` を差し替えると失敗を注入できる（S11 の `FlakyClient`）。"""
    agent = ReActAgent(llm or ScriptedClient(scenario), tools or build_registry(),
                       max_steps=max_steps)
    return agent.run(label, task_id=task_id or f"TASK-{scenario}")


def run_all() -> list[Trajectory]:
    return [run_case(name, label, max_steps) for name, label, max_steps in CASES]


def by_task_id(trajs: list[Trajectory], task_id: str) -> Trajectory:
    for t in trajs:
        if t.task_id == task_id:
            return t
    raise KeyError(f"未知の task_id です: {task_id}")


# ---------------------------------------------------------------------------
# agentkit.trace.Tracer（最小実装）との比較
# ---------------------------------------------------------------------------
def live_tracer_counts() -> dict[str, int]:
    """`ReActAgent(tracer=...)` が集めるスパンの種別と件数。"""
    tracer = Tracer("TASK-expense_report")
    agent = ReActAgent(ScriptedClient("expense_report"), build_registry(), tracer=tracer)
    agent.run("経費レポート作成", task_id="TASK-expense_report")
    return {name: int(row["count"]) for name, row in tracer.breakdown().items()}


def wallclock_is_stable(runs: int = 5) -> bool:
    """実時間トレーサの合計所要が毎回同じ値になるか（＝再現するか）。"""
    totals = set()
    for _ in range(runs):
        tracer = Tracer("TASK-expense_report")
        agent = ReActAgent(ScriptedClient("expense_report"), build_registry(), tracer=tracer)
        agent.run("経費レポート作成", task_id="TASK-expense_report")
        totals.add(round(sum(s.duration_ms for s in tracer.spans), 6))
    return len(totals) == 1


def unit_cost_is_stable(runs: int = 5) -> bool:
    """回数×単価の合計所要が毎回同じ値になるか。"""
    totals = set()
    for _ in range(runs):
        traj = run_case("expense_report", "経費レポート作成")
        totals.add(spans_from_trajectory(traj)[0].ms)
    return len(totals) == 1


def main() -> None:
    reset_data()

    traj = run_case("expense_report", "経費レポート作成")
    spans = spans_from_trajectory(traj)
    print("=== スパンの階層（task → step → tool）===")
    print("\n".join(render_tree(spans)))
    print(f"{census(spans)}  停止理由={traj.stop_reason}")
    print(UNITS_A.describe())

    print("\n=== 相関ID で1件を引く ===")
    target = "expense_report-3-0"
    hits = find_by_call_id(spans, target)
    hit = hits[0]
    print(f"call_id={target} → {hit.span_id}（{hit.kind} {hit.name}・親 {hit.parent_id}）")
    print(f"この call_id を持つスパンは {len(hits)} 件（トレース全体で一意）")
    print("親をたどる: " + " → ".join(ancestors(spans, hit.span_id)))

    print("\n=== agentkit.trace.Tracer（最小実装）と比べる ===")
    print(f"Tracer が集めたスパン: {live_tracer_counts()}")
    print("足りないもの: task スパン / 親子関係 / call_id / 決定的な所要")
    print(f"実時間トレーサ: 5回走らせて合計が毎回同じか → "
          f"{'はい' if wallclock_is_stable() else 'いいえ'}")
    print(f"回数×単価: 5回走らせて合計が毎回同じか → "
          f"{'はい' if unit_cost_is_stable() else 'いいえ'}")

    print("\n=== 失敗した1件（これを次の節で追う）===")
    bad = run_case("max_steps_loop", "同じ検索を繰り返す", 6)
    bad_spans = spans_from_trajectory(bad)
    tool_ids = [s.attrs["call_id"] for s in bad_spans if s.kind == "tool"]
    print(f"{bad.task_id}: 手数={len(bad.steps)} 停止理由={bad.stop_reason} "
          f"{census(bad_spans)} 所要合計={bad_spans[0].ms}ms")
    print(f"ツールスパンの call_id: {tool_ids[0]} … {tool_ids[-1]}")
    path = save_spans(bad_spans, TRACE_DIR / f"{bad.task_id}.spans.jsonl")
    bad.to_jsonl(TRACE_DIR / f"{bad.task_id}.jsonl")
    print(f"保存先: {path.relative_to(ROOT)}")

    reset_data()


if __name__ == "__main__":
    main()
