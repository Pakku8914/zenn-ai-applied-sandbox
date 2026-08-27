#!/usr/bin/env python3
"""ワークフロー版の会議室予約：制御を人間（コード）が握る。

LLM を1回も呼ばない。分岐は「書いた分だけ」存在する。
エージェント版（agent_book_room.py）と同じ業務要求を、同じツールで処理する。
違うのは「次に何をするかを誰が決めるか」だけである。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentkit.biztools import book_room  # noqa: E402
from agentkit.tools import ToolError  # noqa: E402


@dataclass
class WorkflowResult:
    """ワークフローの実行結果。軌跡（Trajectory）の代わりにこれだけで足りる。"""

    ok: bool
    message: str
    tool_calls: list[str] = field(default_factory=list)
    llm_calls: int = 0  # ワークフローは LLM を呼ばないので常に 0


def book_fixed(room: str, start: str, minutes: int = 60) -> WorkflowResult:
    """分岐を1つも持たないワークフロー。

    想定どおりの経路しか通れない。競合したらそこで行き止まりになる。
    """
    calls: list[str] = [f"book_room(room={room}, start={start})"]
    try:
        message = book_room(room, start, minutes)
    except ToolError as exc:
        return WorkflowResult(False, str(exc), calls)
    return WorkflowResult(True, message, calls)


def book_with_fallback(room: str, candidates: list[str],
                       minutes: int = 60) -> WorkflowResult:
    """候補時刻を順に試すワークフロー。

    「競合したら次の候補へ」という分岐を**人間が事前に書いている**。
    列挙した例外にだけ対処できる。列挙できるならこれが最も安く、最も速い。
    """
    calls: list[str] = []
    last_error = ""
    for start in candidates:
        calls.append(f"book_room(room={room}, start={start})")
        try:
            message = book_room(room, start, minutes)
        except ToolError as exc:
            last_error = str(exc)
            continue
        return WorkflowResult(True, message, calls)
    return WorkflowResult(
        False, f"候補をすべて試しましたが確保できませんでした（最後の理由: {last_error}）", calls)


def show(label: str, result: WorkflowResult) -> None:
    print(f"--- {label} ---")
    print(f"LLM 呼び出し: {result.llm_calls} 回 / ツール呼び出し: {len(result.tool_calls)} 回")
    for call in result.tool_calls:
        print(f"  {call}")
    print(f"{'成功' if result.ok else '失敗'}: {result.message}")


def main() -> None:
    print("=== ワークフロー版（分岐なし・みなと 10:00 に固定）===")
    show("分岐なし", book_fixed("みなと", "10:00"))

    print("\n=== ワークフロー版（候補を列挙: 10:00 → 11:00）===")
    show("候補を列挙", book_with_fallback("みなと", ["10:00", "11:00"]))

    print("\n=== 経路が固定できない要求（13:00 に定員10名以上）===")
    show("分岐なし・大会議室 13:00 に固定", book_fixed("大会議室", "13:00"))
    print("※ 定員10名以上の部屋が他にもあることは、このコードには書かれていない。")


if __name__ == "__main__":
    main()
