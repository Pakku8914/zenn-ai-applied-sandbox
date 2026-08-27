"""トレース（セッション14の参照実装）。

スパンの階層（タスク → ステップ → ツール呼び出し）を作り、
どのステップで何秒使い、どれだけトークンを使ったかを後から追えるようにする。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

TRACE_DIR = Path(__file__).resolve().parent.parent / "traces"

# 記録してはいけないキー（秘密情報の露出を防ぐ）
REDACT_KEYS = ("api_key", "password", "token", "secret", "authorization")


def redact(value: dict) -> dict:
    """秘密らしいキーの値を隠す。トレースは長く残るので入口で落とす。"""
    out = {}
    for k, v in value.items():
        if any(bad in k.lower() for bad in REDACT_KEYS):
            out[k] = "***"
        elif isinstance(v, dict):
            out[k] = redact(v)
        elif isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + f"...（{len(v)}文字）"
        else:
            out[k] = v
    return out


@dataclass
class Span:
    name: str
    attrs: dict = field(default_factory=dict)
    start: float = 0.0
    duration_ms: float = 0.0
    depth: int = 0


class Tracer:
    """スパンを集めるだけの最小実装（外部サービスに送らない）。"""

    def __init__(self, task_id: str = "TASK-001") -> None:
        self.task_id = task_id
        self.spans: list[Span] = []
        self._depth = 0

    def span(self, name: str, **attrs) -> "_SpanCtx":
        return _SpanCtx(self, name, redact(attrs))

    def breakdown(self) -> dict[str, dict[str, float]]:
        """スパン名ごとの件数と合計時間。どこに時間を使ったかを見る。"""
        out: dict[str, dict[str, float]] = {}
        for s in self.spans:
            row = out.setdefault(s.name, {"count": 0, "total_ms": 0.0, "max_ms": 0.0})
            row["count"] += 1
            row["total_ms"] += s.duration_ms
            row["max_ms"] = max(row["max_ms"], s.duration_ms)
        return out

    def save(self, path: str | Path | None = None) -> Path:
        p = Path(path) if path else TRACE_DIR / f"{self.task_id}.spans.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps({"name": s.name, "depth": s.depth,
                                    "duration_ms": round(s.duration_ms, 3), "attrs": s.attrs},
                                   ensure_ascii=False) + "\n")
        return p


class _SpanCtx:
    def __init__(self, tracer: Tracer, name: str, attrs: dict) -> None:
        self.tracer = tracer
        self.span = Span(name=name, attrs=attrs, depth=tracer._depth)

    def __enter__(self) -> Span:
        self.span.start = time.perf_counter()
        self.tracer._depth += 1
        return self.span

    def __exit__(self, *exc) -> bool:
        self.span.duration_ms = (time.perf_counter() - self.span.start) * 1000
        self.tracer._depth -= 1
        self.tracer.spans.append(self.span)
        return False
