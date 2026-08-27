#!/usr/bin/env python3
"""計画（サブゴールの DAG）と再計画のトリガ。

S05 で扱った「静的計画／逐次再計画」を、S03 のループと S04 の道具に接続する。
S05 の実装ファイルには依存しない（復習として最小の計画器をここに置く）。

要点は2つある。
  1. 依存関係を宣言すると、実行順は**計算できる**（人が並べ直さない）
  2. 計画を持つと「計画どおりに進んでいない」が**判定できる**。判定できれば
     再計画のトリガになる。計画がないエージェントは、進んでいないことに
     気づけないまま上限まで走る
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SubGoal:
    """計画の1単位。「どの道具で」「何に依存して」達成するかまでを宣言する。"""

    key: str
    tool: str
    depends_on: tuple[str, ...] = ()


@dataclass
class Plan:
    task: str
    goals: list[SubGoal] = field(default_factory=list)

    def keys(self) -> list[str]:
        return [goal.key for goal in self.goals]

    def order(self) -> list[str]:
        """依存関係から実行順を決める（同時に実行できるものは key の辞書順）。

        並びが実行ごとに変わると軌跡が再現しない。辞書順で固定するのは
        「決定的であること」を計画の側でも守るためである。
        """
        pending = {goal.key: set(goal.depends_on) for goal in self.goals}
        if len(pending) != len(self.goals):
            raise ValueError("サブゴールの key が重複しています。")
        unknown = {dep for deps in pending.values() for dep in deps} - set(pending)
        if unknown:
            raise ValueError(f"存在しないサブゴールに依存しています: {sorted(unknown)}")

        done: list[str] = []
        while pending:
            ready = sorted(key for key, deps in pending.items() if not deps - set(done))
            if not ready:
                raise ValueError(f"依存関係が循環しています: {sorted(pending)}")
            for key in ready:
                done.append(key)
                pending.pop(key)
        return done

    def next_ready(self, done) -> list[str]:
        """いま着手できるサブゴール（依存がすべて済んでいるもの）。"""
        done = set(done)
        return sorted(goal.key for goal in self.goals
                      if goal.key not in done and set(goal.depends_on) <= done)

    def remaining_steps(self, done) -> int:
        """残っているサブゴールの数＝最短で必要な残り手数。"""
        done = set(done)
        return sum(1 for goal in self.goals if goal.key not in done)


def trailing_failures(traj) -> tuple[int, str | None]:
    """末尾から連続している失敗の数と、そのツール名を返す。

    「途中で1回失敗した」と「同じ道具で失敗し続けている」は別の症状である。
    前者は回復の途中かもしれないが、後者は計画のまま進めても抜けられない。
    """
    pairs = [(call.name, result.ok)
             for step in traj.steps
             for call, result in zip(step.calls, step.results)]
    count, name = 0, None
    for tool_name, ok in reversed(pairs):
        if ok or (name is not None and tool_name != name):
            break
        name, count = tool_name, count + 1
    return count, name


def failed_tools(traj) -> set[str]:
    return {call.name
            for step in traj.steps
            for call, result in zip(step.calls, step.results)
            if not result.ok}


def should_replan(traj, plan: Plan, *, done, max_steps: int) -> tuple[bool, str]:
    """いま計画を作り直すべきかを判定する。上から順に見て、最初に当たったものを返す。"""
    count, name = trailing_failures(traj)
    if count >= 2:
        return True, f"{name} で2回以上続けて失敗した（同じ計画のまま進めない）"

    broken = sorted(goal.key for goal in plan.goals
                    if goal.key not in set(done) and goal.tool in failed_tools(traj))
    if broken:
        return True, f"前提が崩れた（残っているサブゴール {broken} が使う道具が失敗した）"

    remaining = plan.remaining_steps(done)
    left = max_steps - len(traj.steps)
    if left < remaining + 1:
        return True, (f"残り手数 {left} が計画の残り {remaining}＋報告1手に足りない")

    return False, "計画どおり進められる"


# 経費レポートを作る計画（S02 のワークフロー版と同じ仕事を、依存で表したもの）
REVIEW_PLAN = Plan("今月の経費レポートを作る", [
    SubGoal("policy", "get_policy"),
    SubGoal("expenses", "list_expenses"),
    SubGoal("check", "get_policy", ("policy", "expenses")),
    SubGoal("report", "write_file", ("check",)),
])


def main() -> None:
    print("=== 計画（サブゴールの DAG） ===")
    print(f"タスク: {REVIEW_PLAN.task}")
    print(f"実行順: {REVIEW_PLAN.order()}")
    print(f"いま着手できるもの（何も済んでいない）: {REVIEW_PLAN.next_ready(set())}")
    print(f"policy と expenses が済んだあと: {REVIEW_PLAN.next_ready({'policy', 'expenses'})}")
    print(f"残り手数（2つ済み）: {REVIEW_PLAN.remaining_steps({'policy', 'expenses'})}")

    print("\n=== 循環している計画は実行順を決められない ===")
    cyclic = Plan("循環の例", [SubGoal("a", "get_policy", ("b",)),
                              SubGoal("b", "list_expenses", ("a",))])
    try:
        cyclic.order()
    except ValueError as exc:
        print(f"ValueError: {exc}")


if __name__ == "__main__":
    main()
