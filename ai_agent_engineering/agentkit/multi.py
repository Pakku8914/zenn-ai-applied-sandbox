"""マルチエージェント（セッション8の参照実装）。

分けることで得るもの（責務・権限・並列性）と失うもの（文脈・デバッグ容易性）を
同じコードで比較できるように、最小の型だけを用意する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Trajectory


@dataclass
class Blackboard:
    """エージェント間で共有する黒板。誰が何を書いたかを残す。"""

    entries: list[dict] = field(default_factory=list)

    def write(self, author: str, key: str, value: str) -> None:
        self.entries.append({"author": author, "key": key, "value": value})

    def read(self, key: str) -> list[str]:
        return [e["value"] for e in self.entries if e["key"] == key]

    def latest(self, key: str) -> str | None:
        values = self.read(key)
        return values[-1] if values else None


@dataclass
class Handoff:
    """次に処理を渡す相手と、渡す情報。

    自由文で渡すと情報が落ちる（伝言ゲーム）。構造化して渡すのが要点。
    """

    to: str
    task: str
    context: dict = field(default_factory=dict)


class Orchestrator:
    """親が子エージェントに仕事を配り、結果を集める。"""

    def __init__(self, workers: dict[str, object], blackboard: Blackboard | None = None) -> None:
        self.workers = workers
        self.blackboard = blackboard or Blackboard()
        self.trajectories: dict[str, Trajectory] = {}

    def dispatch(self, name: str, task: str, task_id: str) -> Trajectory:
        worker = self.workers.get(name)
        if worker is None:
            raise ValueError(f"未登録のワーカーです: {name}（登録済み: {sorted(self.workers)}）")
        traj = worker.run(task, task_id=task_id)
        self.trajectories[name] = traj
        self.blackboard.write(name, "result", traj.final or "")
        return traj

    def run_sequence(self, plan: list[Handoff], task_id_prefix: str = "TASK") -> list[Trajectory]:
        out: list[Trajectory] = []
        for i, step in enumerate(plan, start=1):
            # 前段の結果を構造化して渡す（自由文で渡さない）
            context = dict(step.context)
            if i > 1:
                context["previous_result"] = self.blackboard.latest("result") or ""
            task = step.task if not context else (
                step.task + "\n\n# 引き継ぎ情報\n"
                + "\n".join(f"- {k}: {v}" for k, v in context.items())
            )
            out.append(self.dispatch(step.to, task, f"{task_id_prefix}-{i:02d}"))
        return out

    def total_tokens(self) -> dict[str, int]:
        total = {"input": 0, "output": 0}
        for traj in self.trajectories.values():
            t = traj.total_tokens
            total["input"] += t["input"]
            total["output"] += t["output"]
        return total
