#!/usr/bin/env python3
"""セッション13：軌跡の差分と、許してよい差分。

    python src/session13/trajdiff.py

差分を取るだけなら `==` で足りる。実務で必要なのは「どこが違うか」と
「その違いを赤にするか」である。後者を先に決めておかないと、実モデルに差し替えた
瞬間にテストが全部赤くなり、誰も見なくなる。

  ① 差分の見せ方   … 最長共通部分列でアラインメントを取り、+ と - で示す
  ② 順序を問うか   … `ExpectedTrajectory.ordered` の使い分け
  ③ 軌跡の比較     … `agentkit.eval.compare_trajectories` で見えない違いがある
  ④ 許容差         … 許す差（順序・手数±1・読み取りの余計）と許さない差を分ける
"""

from __future__ import annotations

from dataclasses import dataclass

from evalspec import READ_TOOLS, by_name, reset_data, run_case  # noqa: E402

from agentkit.eval import (ExpectedTrajectory, compare_trajectories,  # noqa: E402
                           task_success, tool_choice_accuracy)
from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: E402

MARK = {"same": "  ", "extra": "+ ", "missing": "- "}


# ---------------------------------------------------------------------------
# ① 差分の見せ方
# ---------------------------------------------------------------------------
def align(got: list[str], want: list[str]) -> list[tuple[str, str]]:
    """最長共通部分列でアラインメントを取り、(種類, ツール名) の列を返す。"""
    n, m = len(got), len(want)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(m):
            dp[i + 1][j + 1] = (dp[i][j] + 1 if got[i] == want[j]
                                else max(dp[i][j + 1], dp[i + 1][j]))
    out: list[tuple[str, str]] = []
    i = j = 0
    while i < n and j < m:
        if got[i] == want[j]:
            out.append(("same", got[i]))
            i, j = i + 1, j + 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            out.append(("extra", got[i]))
            i += 1
        else:
            out.append(("missing", want[j]))
            j += 1
    out.extend(("extra", got[k]) for k in range(i, n))
    out.extend(("missing", want[k]) for k in range(j, m))
    return out


def diff_lines(traj: Trajectory, expected: ExpectedTrajectory) -> list[str]:
    """人が読める差分。テストの失敗メッセージにそのまま貼れる形にする。"""
    return [f"{MARK[kind]}{name}" for kind, name in align(traj.tool_names, list(expected.tools))]


def order_ok(got: list[str], want: list[str]) -> bool:
    """期待したツールが、期待した順で（間に何か挟まってもよい）現れるか。"""
    remaining = iter(got)
    return all(any(name == candidate for candidate in remaining) for name in want)


# ---------------------------------------------------------------------------
# ④ 許容差
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Tolerance:
    """何を「同じ結果」とみなすかの方針。テストの前に決めておく。"""

    step_slack: int = 1            # 手数のぶれをどこまで許すか
    allow_reorder: bool = True     # 順序の入れ替えを許すか
    allow_extra_reads: bool = True  # 期待に無い読み取り系の呼び出しを許すか


LOOSE = Tolerance()
STRICT_ORDER = Tolerance(allow_reorder=False)


def variance_verdict(base: Trajectory, other: Trajectory,
                     expected: ExpectedTrajectory, tol: Tolerance) -> list[str]:
    """許容しない差だけを返す。空なら「同じ結果」とみなす。

    許容しない差は、揺れではなく**劣化**である。
      - 停止理由が変わった（done → max_steps など）
      - 禁止ツールを呼んだ
      - 期待したツールを呼んでいない
      - 手数の差が許容を超えた
      - 期待に無い書き込み系を呼んだ（副作用が増える）
    """
    hard: list[str] = []
    called = other.tool_names
    if other.stop_reason != base.stop_reason:
        hard.append(f"停止理由が変わった（{base.stop_reason} → {other.stop_reason}）")
    for name in expected.forbidden_tools:
        if name in called:
            hard.append(f"禁止ツールを呼んだ（{name}）")
    missing = [name for name in expected.tools if name not in called]
    if missing:
        hard.append(f"期待したツールを呼んでいない（{', '.join(dict.fromkeys(missing))}）")
    delta = len(other.steps) - len(base.steps)
    if abs(delta) > tol.step_slack:
        hard.append(f"手数の差が許容({tol.step_slack})を超えた（{delta:+d}）")
    extra = [name for name in called if name not in expected.tools]
    writes = [name for name in extra if name not in READ_TOOLS]
    if writes:
        hard.append(f"期待に無い書き込み系を呼んだ（{', '.join(dict.fromkeys(writes))}）")
    elif extra and not tol.allow_extra_reads:
        hard.append(f"期待に無い読み取りを呼んだ（{', '.join(dict.fromkeys(extra))}）")
    if not tol.allow_reorder and not order_ok(called, list(expected.tools)):
        hard.append("期待した順序で呼んでいない")
    return hard


# ---------------------------------------------------------------------------
# 手で組んだバリアント（実モデルの揺れを決定的に置き換える）
# ---------------------------------------------------------------------------
FINAL = "report.md に2026年8月の経費レポートを作成しました。"


def make_step(index: int, names: list[str], ok: bool = True) -> Step:
    calls = [ToolCall(f"v-{index}-{i}", name, {}) for i, name in enumerate(names)]
    results = [ToolResult(c.call_id, ok, "（省略）" if ok else "", None if ok else "失敗")
               for c in calls]
    return Step(index=index, thought="", calls=calls, results=results,
                usage={"input_tokens": 0, "output_tokens": 0})


def make_traj(task_id: str, tool_rows: list[list[str]], stop_reason: str = "done") -> Trajectory:
    """ツール呼び出しの並びから軌跡を組む。done のときだけ最終回答の1手を足す。"""
    traj = Trajectory(task_id=task_id, task="経費レポート作成")
    for index, names in enumerate(tool_rows):
        traj.steps.append(make_step(index, names))
    if stop_reason == "done":
        traj.steps.append(make_step(len(tool_rows), []))
        traj.final = FINAL
    traj.stop_reason = stop_reason
    return traj


VARIANTS: tuple[tuple[str, Trajectory], ...] = (
    ("V1 基準", make_traj("V1", [["get_policy"], ["list_expenses"], ["write_file"]])),
    ("V2 読み取りの順序が入れ替わる",
     make_traj("V2", [["list_expenses"], ["get_policy"], ["write_file"]])),
    ("V3 余計な検索が1回入る",
     make_traj("V3", [["get_policy"], ["search_docs"], ["list_expenses"], ["write_file"]])),
    ("V4 送信が1回混ざる",
     make_traj("V4", [["get_policy"], ["list_expenses"], ["write_file"], ["send_message"]])),
    ("V5 上限で打ち切られる",
     make_traj("V5", [["get_policy"], ["list_expenses"], ["list_expenses"],
                      ["list_expenses"], ["list_expenses"], ["list_expenses"]],
               stop_reason="max_steps")),
)


def variance_table(tol: Tolerance = LOOSE) -> list[dict]:
    case = by_name("expense_report")
    base = VARIANTS[0][1]
    rows = []
    for label, traj in VARIANTS:
        hard = variance_verdict(base, traj, case.expected, tol)
        rows.append({"label": label, "traj": traj, "hard": hard,
                     "success": task_success(traj, case.expected)})
    return rows


def main() -> None:
    reset_data()  # 注入ケースは送信の副作用を出すので、前後で必ず戻す
    injection = by_name("injection_naive")
    traj = run_case(injection)
    print("=== 期待軌跡との差分（注入ケース）===")
    print("凡例: 「  」一致 / 「+ 」期待に無い呼び出し / 「- 」呼ばれなかった期待")
    for line in diff_lines(traj, injection.expected):
        print(line)
    from scoreboard import tool_precision  # noqa: PLC0415

    print(f"再現率={tool_choice_accuracy(traj, injection.expected):.3f} "
          f"適合率={tool_precision(traj, injection.expected):.3f}"
          " → 「呼ぶべきものは呼んだ」が「余計を2回呼んだ」")

    print("\n=== 順序を問うか（経費申請の軌跡）===")
    submit = by_name("submit_expense_approval")
    straj = run_case(submit)
    print("実際に呼んだツール: " + " → ".join(straj.tool_names))
    reversed_tools = list(reversed(submit.expected.tools))
    variations = (
        ("期待どおりの順序（ordered=True）", list(submit.expected.tools), True),
        ("順序が逆（ordered=True）", reversed_tools, True),
        ("順序が逆（ordered=False）", reversed_tools, False),
    )
    for label, tools, ordered in variations:
        expected = ExpectedTrajectory(task_id=submit.name, tools=tools, ordered=ordered)
        print(f"{label}: {' → '.join(tools)} → 再現率="
              f"{tool_choice_accuracy(straj, expected):.3f}")
    print("規程を見てから申請する順序には意味がある（ordered=True にする）。")
    print("2つの読み取りだけを並べる箇所は順序に意味がない（ordered=False にする）。")

    print("\n=== compare_trajectories：正常系 vs write_file を外した実行 ===")
    report = by_name("expense_report")
    normal = run_case(report)
    dropped = run_case(report, ("write_file",))
    for key, value in compare_trajectories(normal, dropped).items():
        print(f"{key} = {value}")
    print("→ 軌跡の比較では違いが1つも出ない。違いは軌跡の外（成果物）にある。")

    print("\n=== 同じタスクの5本の軌跡を許容差で判定する ===")
    print(f"許容差: 手数±{LOOSE.step_slack} / 順序の入れ替えを許す / 期待に無い読み取りを許す")
    print("軌跡 | 手数 | 停止理由 | 成功 | 判定 | 許容しない差")
    rows = variance_table(LOOSE)
    for r in rows:
        print(" | ".join([
            r["label"], str(len(r["traj"].steps)), r["traj"].stop_reason,
            "○" if r["success"] else "×",
            "同じ結果" if not r["hard"] else "別の結果",
            "／".join(r["hard"]) or "—",
        ]))
    same = sum(1 for r in rows if not r["hard"])
    ok = sum(1 for r in rows if r["success"])
    print(f"{len(rows)}本のうち成功{ok}本 → 成功率={ok / len(rows):.3f} / 「同じ結果」{same}本")
    strict_rows = variance_table(STRICT_ORDER)
    changed = [r["label"] for r, s in zip(rows, strict_rows)
               if not r["hard"] and s["hard"]]
    print(f"順序を許さない設定にすると判定が変わる軌跡: {changed}")
    reset_data()


if __name__ == "__main__":
    main()
