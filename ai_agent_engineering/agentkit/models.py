"""章をまたいで共有するデータ構造。

ここで定義した型は「API契約」であり、章の途中で名前や型を変えない。
（requirements.md の「API契約」を参照）
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# 停止理由。あとから型を変えないよう、使う予定のものを最初から並べておく
STOP_REASONS = ("done", "max_steps", "budget", "error", "awaiting_approval", "loop_detected")


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    ok: bool
    content: str
    error: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    """LLM の1回の応答。ツール呼び出しか最終回答のどちらか。"""

    thought: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    final: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    source: str = "scripted"  # scripted / fixture / api


@dataclass
class Step:
    index: int
    thought: str
    calls: list[ToolCall] = field(default_factory=list)
    results: list[ToolResult] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


@dataclass
class Trajectory:
    """エージェントが何をしたかの記録。評価とデバッグの単位。"""

    task_id: str
    task: str = ""
    steps: list[Step] = field(default_factory=list)
    final: str | None = None
    stop_reason: str = "done"

    @property
    def tool_names(self) -> list[str]:
        """呼ばれたツール名を順に並べたもの（軌跡の比較に使う）。"""
        return [c.name for s in self.steps for c in s.calls]

    @property
    def total_tokens(self) -> dict[str, int]:
        return {
            "input": sum(s.usage.get("input_tokens", 0) for s in self.steps),
            "output": sum(s.usage.get("output_tokens", 0) for s in self.steps),
        }

    def to_jsonl(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "task", "task_id": self.task_id, "task": self.task,
                                "stop_reason": self.stop_reason, "final": self.final},
                               ensure_ascii=False) + "\n")
            for s in self.steps:
                f.write(json.dumps({"type": "step", **asdict(s)}, ensure_ascii=False) + "\n")

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "Trajectory":
        rows = [json.loads(line) for line in Path(path).open(encoding="utf-8") if line.strip()]
        head = next(r for r in rows if r["type"] == "task")
        traj = cls(task_id=head["task_id"], task=head.get("task", ""),
                   final=head.get("final"), stop_reason=head.get("stop_reason", "done"))
        for r in rows:
            if r["type"] != "step":
                continue
            traj.steps.append(Step(
                index=r["index"], thought=r["thought"],
                calls=[ToolCall(**c) for c in r["calls"]],
                results=[ToolResult(**x) for x in r["results"]],
                usage=r.get("usage", {}),
            ))
        return traj
