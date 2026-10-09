"""練習問題6の解答：1回のループの中で、同じツールを同じ引数で呼び直したら実行せずに is_error で返す。"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import replace

from .tools import Tool, ToolContext, ToolError, ToolInput

DUPLICATE = "{name} は同じ引数ですでに呼びました。前の tool_result を使って続けてください。"


def dedup_tools(tools: Mapping[str, Tool]) -> dict[str, Tool]:
    """リクエストごとに1回呼び、返った登録簿を run_tool_loop(tools=...) に渡す（seen はそのループ専用）。"""
    seen: set[tuple[str, str]] = set()

    def wrap(tool: Tool) -> Tool:
        async def run(args: ToolInput, ctx: ToolContext) -> dict:
            key = (tool.name, args.model_dump_json())  # 検証後のモデルで比べる＝既定値やキーの順の違いを吸収
            if key in seen:
                raise ToolError(DUPLICATE.format(name=tool.name))
            seen.add(key)
            out = tool.run(args, ctx)
            return await out if inspect.isawaitable(out) else out

        return replace(tool, run=run)

    return {name: wrap(t) for name, t in tools.items()}
