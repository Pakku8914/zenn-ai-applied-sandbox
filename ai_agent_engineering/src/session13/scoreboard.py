#!/usr/bin/env python3
"""セッション13：スコアカード — 品質とコストを同じ表に並べる。

    python src/session13/scoreboard.py

測る指標は5系統ある。**別々に測る**のが要点で、1つに混ぜると原因が消える。

  ① タスク成功率     … 期待した結果に到達したか（`agentkit.eval.task_success`）
  ② 期待整合率       … 「失敗すべきケースが期待どおり失敗したか」も含めて数える
  ③ ツール選択       … 再現率（呼ぶべきものを呼んだか）と適合率（余計を呼ばなかったか）
  ④ 手数             … 平均だけでなく分布（中央値・最大）を見る
  ⑤ コスト・レイテンシ … 近似トークン数と段数。品質の隣に置いて初めて比較になる

再現率は `agentkit.eval.tool_choice_accuracy` をそのまま使う。適合率は agentkit に
無いので本章で足す（agentkit は変更しない）。
"""

from __future__ import annotations

import statistics
from collections import Counter

from evalspec import CASES, Case, reset_data, run_all  # noqa: E402

from agentkit.eval import ExpectedTrajectory, task_success, tool_choice_accuracy  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402

# `tools/traj_stats.py`（2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB /
# Python 3.12.13）の出力を転記した静的な表。**別実行の測定値**なので、この章の
# 走行で得たトークン数と足し合わせて比較してはいけない。
# トークン数は決定的な近似値（プロンプトの文字数 ÷ 3）であり、実 API の計測値ではない。
TRAJ_STATS: tuple[tuple[str, int, int, int], ...] = (
    ("経費レポート作成", 4, 1022, 48),
    ("会議室予約（競合あり）", 3, 436, 35),
    ("経費申請（5万円以上）", 3, 449, 34),
    ("隔離実行で集計", 3, 722, 23),
    ("同じ検索を繰り返す", 6, 2966, 12),
)


# ---------------------------------------------------------------------------
# 指標
# ---------------------------------------------------------------------------
def matched(got: list[str], want: list[str], ordered: bool = True) -> int:
    """期待に対応づけられた呼び出しの数。順序を問う場合は最長共通部分列で測る。

    `agentkit.eval.tool_choice_accuracy` と同じ数え方（あちらは割った値だけを返す）。
    """
    if not want or not got:
        return 0
    if not ordered:
        c_got, c_want = Counter(got), Counter(want)
        return sum(min(c_got[key], c_want[key]) for key in c_want)
    n, m = len(got), len(want)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(m):
            dp[i + 1][j + 1] = (dp[i][j] + 1 if got[i] == want[j]
                                else max(dp[i][j + 1], dp[i + 1][j]))
    return dp[n][m]


def tool_recall(traj: Trajectory, expected: ExpectedTrajectory) -> float:
    """呼ぶべきツールをどれだけ呼んだか。既存実装をそのまま使う。"""
    return tool_choice_accuracy(traj, expected)


def tool_precision(traj: Trajectory, expected: ExpectedTrajectory) -> float:
    """呼んだツールのうち、期待に対応づけられた割合。**余計な呼び出しを罰する**。"""
    got = traj.tool_names
    if not got:
        return 1.0 if not expected.tools else 0.0
    return matched(got, list(expected.tools), expected.ordered) / len(got)


def extra_calls(traj: Trajectory, expected: ExpectedTrajectory) -> int:
    """期待に対応づけられなかった呼び出しの回数。"""
    got = traj.tool_names
    return len(got) - matched(got, list(expected.tools), expected.ordered)


def depth(traj: Trajectory) -> int:
    """段数（直列に並ぶ LLM 呼び出しの段数）。単体エージェントでは手数と一致する。

    レイテンシの代理指標。マルチエージェント（S08）では並列に走る枝があるので乖離する。
    """
    return len(traj.steps)


def max_parallel(traj: Trajectory) -> int:
    """1ステップで同時に呼んだツールの最大数（並列ツール呼び出しの有無）。"""
    return max((len(step.calls) for step in traj.steps), default=0)


def as_declared(traj: Trajectory, case: Case) -> bool:
    """宣言どおりの結果になったか。成功すべきは成功し、失敗すべきは失敗すること。"""
    return task_success(traj, case.expected) == case.expect_success


def row(case: Case, traj: Trajectory) -> dict:
    return {
        "case": case.name,
        "success": task_success(traj, case.expected),
        "expect": case.expect_success,
        "as_declared": as_declared(traj, case),
        "recall": tool_recall(traj, case.expected),
        "precision": tool_precision(traj, case.expected),
        "extra": extra_calls(traj, case.expected),
        "steps": len(traj.steps),
        "stop_reason": traj.stop_reason,
        "parallel": max_parallel(traj),
    }


def summarize(pairs: list[tuple[Case, Trajectory]]) -> dict:
    rows = [row(case, traj) for case, traj in pairs]
    steps = [r["steps"] for r in rows]
    n = len(rows)
    return {
        "n": n,
        "rows": rows,
        "success_rate": sum(r["success"] for r in rows) / n,
        "declared_rate": sum(r["as_declared"] for r in rows) / n,
        "recall": sum(r["recall"] for r in rows) / n,
        "precision": sum(r["precision"] for r in rows) / n,
        "extra": sum(r["extra"] for r in rows),
        "mean_steps": sum(steps) / n,
        "min_steps": min(steps),
        "median_steps": statistics.median(steps),
        "max_steps": max(steps),
        "dist": dict(sorted(Counter(steps).items())),
        "parallel": max(r["parallel"] for r in rows),
    }


def main() -> None:
    reset_data()
    pairs = run_all()
    summary = summarize(pairs)

    print("=== 6ケースの評価（品質）===")
    print("ケース | 判定 | 期待 | 期待どおり | 再現率 | 適合率 | 余計 | 手数 | 停止理由")
    for r in summary["rows"]:
        print(" | ".join([
            r["case"],
            "○" if r["success"] else "×",
            "成功" if r["expect"] else "失敗すべき",
            "○" if r["as_declared"] else "×",
            f"{r['recall']:.3f}",
            f"{r['precision']:.3f}",
            str(r["extra"]),
            str(r["steps"]),
            r["stop_reason"],
        ]))

    print(f"\nn={summary['n']} タスク成功率={summary['success_rate']:.3f} "
          f"期待整合率={summary['declared_rate']:.3f}")
    print(f"ツール選択: 再現率={summary['recall']:.3f} 適合率={summary['precision']:.3f} "
          f"余計な呼び出し={summary['extra']} 回")
    print(f"手数: 平均={summary['mean_steps']:.2f} 最小={summary['min_steps']} "
          f"中央値={summary['median_steps']:.1f} 最大={summary['max_steps']} "
          f"分布={summary['dist']}")
    print(f"段数（レイテンシの代理）＝手数 / 並列ツール呼び出しの最大={summary['parallel']}")
    failed = [r for r in summary["rows"] if not r["success"]]
    print("失敗したケース: " + ", ".join(
        f"{r['case']}（{r['stop_reason']}・{'期待どおり' if r['as_declared'] else '想定外'}）"
        for r in failed))

    print("\n=== コスト（近似トークン数＝プロンプトの文字数÷3・比較用）===")
    print("出典: tools/traj_stats.py（2026-08-15 実測・別実行）。上の走行の数値とは足し合わせない。")
    print("シナリオ | 手数 | 近似in | 近似out | 1手あたりの近似in")
    for name, steps, tin, tout in TRAJ_STATS:
        print(f"{name} | {steps} | {tin} | {tout} | {tin / steps:.1f}")
    small, big = TRAJ_STATS[0], TRAJ_STATS[-1]
    print(f"手数 {small[1]}→{big[1]}（{big[1] / small[1]:.1f}倍）で "
          f"近似入力トークンは {small[2]}→{big[2]}（{big[2] / small[2]:.2f}倍）。"
          "コストは手数に比例せず、履歴の再送で二次的に膨らむ。")

    reset_data()
    print(f"\n※ 期待どおりでないケース: "
          f"{[r['case'] for r in summary['rows'] if not r['as_declared']] or 'なし'}")
    print(f"※ 評価したケース数は {len(CASES)} 件。data/ は初期状態に戻しました。")


if __name__ == "__main__":
    main()
