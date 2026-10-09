"""練習問題7の解答：1ステップに来た複数の tool_use を、同時実行数と呼び出し数に上限を置いて並行に実行する。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from .loop import ToolLimits, ToolResult, execute_tool
from .providers import ToolCall
from .tools import TOOLS, Tool, ToolContext

TOO_MANY = "1回の応答で呼べるツールは {max_calls} つまでです。必要なら次の応答で呼んでください。"


async def execute_all(calls: list[ToolCall], ctx: ToolContext, *, tools: Mapping[str, Tool] = TOOLS,
                      limits: ToolLimits = ToolLimits(), max_parallel: int = 2,
                      max_calls: int = 3) -> list[ToolResult]:
    """結果は calls と同じ順で返す（tool_result の並びを tool_use の並びにそろえるため）。"""
    gate = asyncio.Semaphore(max_parallel)
    results: list[ToolResult | None] = [None] * len(calls)

    async def one(i: int, call: ToolCall) -> None:
        async with gate:  # 同時に動くのは max_parallel 個まで
            results[i] = await execute_tool(call, ctx, tools=tools, limits=limits)

    async with asyncio.TaskGroup() as tg:  # どれかで止められたら（キャンセル）、残りもまとめて止まる
        for i, call in enumerate(calls):
            if i < max_calls:
                tg.create_task(one(i, call))
            else:
                results[i] = ToolResult(call.id, call.name, TOO_MANY.format(max_calls=max_calls), True)
    return [r for r in results if r is not None]
