#!/usr/bin/env python3
"""ツール側の障害を決定的に注入する（セッション11）。

`agentkit.llm.FlakyClient` は **LLM 側**の失敗を注入する。ここで足すのは
**ツール側**の失敗で、要点は2種類あることである。

  when="before" … 副作用を出す前に失敗する（相手には何も届いていない）
  when="after"  … 副作用を出したあとに失敗する（相手ではもう成功している）

呼び出した側から見ると、この2つは**同じ「失敗しました」にしか見えない**。
「失敗したから、もう一度」が成立しないのはこのためである。
失敗は乱数ではなく「N 回目の呼び出し」で決定的に注入する（軌跡を再現するため）。
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.tools import Tool, ToolError  # noqa: E402

AFTER_MESSAGE = ("経費システムから応答が返りませんでした（タイムアウト）。"
                 "申請が登録されたかどうかは確認できません。")
BEFORE_MESSAGE = ("経費システムに接続できませんでした（一時的な障害）。"
                  "しばらく待ってから同じ内容で再実行してください。")
CHAT_MESSAGE = ("社内チャットに接続できませんでした（一時的な障害）。"
                "しばらく待ってから再送してください。")


class FaultInjector:
    """関数を包み、指定回の呼び出しで `ToolError` を投げる。"""

    def __init__(self, fn: Callable[..., str], *, fail_on: tuple[int, ...] = (1,),
                 when: str = "after", message: str | None = None) -> None:
        if when not in ("before", "after"):
            raise ValueError(f"when は before か after です: {when!r}")
        self.fn = fn
        self.fail_on = set(fail_on)
        self.when = when
        self.message = message or (AFTER_MESSAGE if when == "after" else BEFORE_MESSAGE)
        self.count = 0  # 何回呼ばれたか（副作用の回数の照合に使う）

    def __call__(self, **kwargs) -> str:
        self.count += 1
        hit = self.count in self.fail_on
        if hit and self.when == "before":
            raise ToolError(self.message)
        out = self.fn(**kwargs)   # ここで副作用が起きる
        if hit:
            raise ToolError(self.message)
        return out


def flaky_tool(tool: Tool, **kwargs) -> Tool:
    """既存の Tool を、失敗を注入する版に差し替える。

    宣言（name / description / schema / idempotent）は変えない。
    変えるのは実装だけである。モデルから見た世界は同じままにしておく。
    """
    return replace(tool, fn=FaultInjector(tool.fn, **kwargs))


if __name__ == "__main__":
    def _add(**kwargs) -> str:
        _add.calls += 1  # type: ignore[attr-defined]
        return f"実行しました（通算 {_add.calls} 回目）"  # type: ignore[attr-defined]

    _add.calls = 0  # type: ignore[attr-defined]

    for label, when in (("before（副作用の前に失敗）", "before"),
                        ("after（副作用のあとに失敗）", "after")):
        _add.calls = 0  # type: ignore[attr-defined]
        injected = FaultInjector(_add, fail_on=(1,), when=when)
        try:
            injected()
        except ToolError as exc:
            print(f"{label}: 失敗 — {exc}")
        print(f"  実際に実行された回数: {_add.calls}")  # type: ignore[attr-defined]
