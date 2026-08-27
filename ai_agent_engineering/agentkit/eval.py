"""軌跡の評価（セッション13の参照実装）。

最終出力だけを見る評価では「偶然当たった軌跡」と「正しい軌跡」が区別できない。
過程（どのツールをどの順で呼んだか）も測る。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Trajectory


@dataclass
class ExpectedTrajectory:
    """期待する軌跡。順序を問うかどうかを選べる。"""

    task_id: str
    tools: list[str]                      # 呼ばれるべきツール名（順序つき）
    ordered: bool = True                  # 順序も一致を要求するか
    forbidden_tools: list[str] = field(default_factory=list)  # 呼んではいけないツール
    final_contains: list[str] = field(default_factory=list)   # 最終回答に含まれるべき語
    max_steps: int | None = None


def tool_choice_accuracy(traj: Trajectory, expected: ExpectedTrajectory) -> float:
    """ツール選択の正しさ。順序を問う場合は最長共通部分列で測る。"""
    got, want = traj.tool_names, expected.tools
    if not want:
        return 1.0 if not got else 0.0
    if not expected.ordered:
        from collections import Counter

        c_got, c_want = Counter(got), Counter(want)
        matched = sum(min(c_got[k], c_want[k]) for k in c_want)
        return matched / len(want)
    # 最長共通部分列（順序を保った一致の長さ）
    n, m = len(got), len(want)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(m):
            dp[i + 1][j + 1] = dp[i][j] + 1 if got[i] == want[j] else max(dp[i][j + 1], dp[i + 1][j])
    return dp[n][m] / m


def task_success(traj: Trajectory, expected: ExpectedTrajectory) -> bool:
    """タスクが成功したか。禁止ツールを呼んでいたら失敗とする。"""
    if traj.stop_reason != "done":
        return False
    if any(name in traj.tool_names for name in expected.forbidden_tools):
        return False
    if expected.max_steps is not None and len(traj.steps) > expected.max_steps:
        return False
    final = traj.final or ""
    return all(word in final for word in expected.final_contains)


def compare_trajectories(a: Trajectory, b: Trajectory) -> dict:
    """2つの軌跡の差分。モデル差し替えの影響を見るのに使う。"""
    return {
        "same_tools": a.tool_names == b.tool_names,
        "only_in_a": [t for t in a.tool_names if t not in b.tool_names],
        "only_in_b": [t for t in b.tool_names if t not in a.tool_names],
        "steps": (len(a.steps), len(b.steps)),
        "stop_reason": (a.stop_reason, b.stop_reason),
        "same_final": (a.final or "") == (b.final or ""),
    }


@dataclass
class EvalSummary:
    n: int = 0
    success: int = 0
    tool_acc_sum: float = 0.0
    steps_sum: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.success / self.n if self.n else 0.0

    @property
    def tool_choice_accuracy(self) -> float:
        return self.tool_acc_sum / self.n if self.n else 0.0

    @property
    def mean_steps(self) -> float:
        return self.steps_sum / self.n if self.n else 0.0

    def summary(self) -> str:
        return (f"n={self.n} 成功率={self.success_rate:.3f} "
                f"ツール選択正解率={self.tool_choice_accuracy:.3f} "
                f"平均手数={self.mean_steps:.2f} "
                f"トークン(in/out)={self.tokens_in}/{self.tokens_out}")


def evaluate(pairs: list[tuple[Trajectory, ExpectedTrajectory]]) -> EvalSummary:
    s = EvalSummary()
    for traj, expected in pairs:
        s.n += 1
        ok = task_success(traj, expected)
        s.success += int(ok)
        s.tool_acc_sum += tool_choice_accuracy(traj, expected)
        s.steps_sum += len(traj.steps)
        total = traj.total_tokens
        s.tokens_in += total["input"]
        s.tokens_out += total["output"]
        if not ok:
            s.failures.append(f"{traj.task_id}（stop_reason={traj.stop_reason}）")
    return s
