"""練習問題4の解答：ToolCallStart と ToolCallDelta だけから、ツール呼び出しを組み立て直す。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from .providers import StreamEvent, ToolCall, ToolCallDelta, ToolCallStart


@dataclass(frozen=True)
class BrokenToolCall:
    """引数の JSON が最後まで読めなかった呼び出し。実行せず、is_error の結果にする。"""

    id: str
    name: str
    raw: str


def assemble_tool_calls(events: Iterable[StreamEvent]) -> list[ToolCall | BrokenToolCall]:
    started: dict[str, str] = {}  # id → name（開始した順を保つ）
    parts: dict[str, list[str]] = {}
    for ev in events:
        if isinstance(ev, ToolCallStart):
            started[ev.id] = ev.name
            parts[ev.id] = []
        elif isinstance(ev, ToolCallDelta):
            parts[ev.id].append(ev.partial_json)  # 断片のたびに json.loads しない（途中は JSON ではない）
    out: list[ToolCall | BrokenToolCall] = []
    for id_, name in started.items():
        raw = "".join(parts[id_])
        try:
            value = json.loads(raw) if raw else {}  # 引数なしのツールは断片が1つも来ない
        except json.JSONDecodeError:
            out.append(BrokenToolCall(id_, name, raw))
            continue
        out.append(ToolCall(id_, name, value) if isinstance(value, dict) else BrokenToolCall(id_, name, raw))
    return out
