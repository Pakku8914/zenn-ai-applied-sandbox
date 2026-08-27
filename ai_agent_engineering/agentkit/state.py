"""状態とチェックポイント（セッション6の参照実装）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import Trajectory

CHECKPOINT_DIR = Path(__file__).resolve().parent.parent / "traces" / "checkpoints"


@dataclass
class Checkpoint:
    """どこまで進んだかの保存。軌跡＋アプリケーション状態を1つにまとめる。"""

    task_id: str
    trajectory: Trajectory
    state: dict = field(default_factory=dict)

    def save(self, directory: Path | None = None) -> Path:
        directory = directory or CHECKPOINT_DIR
        directory.mkdir(parents=True, exist_ok=True)
        traj_path = directory / f"{self.task_id}.traj.jsonl"
        self.trajectory.to_jsonl(traj_path)
        meta = directory / f"{self.task_id}.state.json"
        # 一時ファイルに書いてから rename する（部分書き込みを読ませない）
        tmp = directory / f"{self.task_id}.state.tmp"
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(meta)
        return meta

    @classmethod
    def load(cls, task_id: str, directory: Path | None = None) -> "Checkpoint":
        directory = directory or CHECKPOINT_DIR
        traj = Trajectory.from_jsonl(directory / f"{task_id}.traj.jsonl")
        state_path = directory / f"{task_id}.state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        return cls(task_id=task_id, trajectory=traj, state=state)

    @classmethod
    def exists(cls, task_id: str, directory: Path | None = None) -> bool:
        directory = directory or CHECKPOINT_DIR
        return (directory / f"{task_id}.traj.jsonl").exists()


class Machine:
    """有限状態機械。エージェントの進行を「状態」と「遷移」で表す。

    transitions: {現在の状態: {イベント: 次の状態}}
    """

    def __init__(self, initial: str, transitions: dict[str, dict[str, str]]) -> None:
        self.state = initial
        self.transitions = transitions
        self.history: list[tuple[str, str, str]] = []

    def fire(self, event: str) -> str:
        allowed = self.transitions.get(self.state, {})
        if event not in allowed:
            raise ValueError(
                f"状態 '{self.state}' でイベント '{event}' は許可されていません"
                f"（許可: {sorted(allowed)}）"
            )
        prev, self.state = self.state, allowed[event]
        self.history.append((prev, event, self.state))
        return self.state

    def can(self, event: str) -> bool:
        return event in self.transitions.get(self.state, {})

    def to_mermaid(self) -> str:
        """状態遷移図を Mermaid で出力する（章の図をコードから生成できる）。"""
        lines = ["stateDiagram-v2"]
        for src, events in self.transitions.items():
            for event, dst in events.items():
                lines.append(f"    {src} --> {dst}: {event}")
        return "\n".join(lines)
