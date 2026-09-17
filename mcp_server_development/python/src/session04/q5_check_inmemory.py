"""別解: 子プロセスを起こさずに同じ検証を行う（起動コストがゼロ）

MCPServer のメソッドを直接呼びます。失敗は例外として上がるので、
異常系は try / except で受けます（stdio 経由との違い）。
"""

import asyncio
import sys

from create_server import mcp


async def main() -> int:
    results: list[bool] = []

    tools = await mcp.list_tools()
    results.append(
        sorted(tool.name for tool in tools) == ["list_members", "summarize_hours"]
    )

    normal = await mcp.call_tool(
        "summarize_hours", {"start_date": "2026-08-03", "end_date": "2026-08-07"}
    )
    results.append("合計 56 時間" in getattr(normal.content[0], "text", ""))

    try:
        await mcp.call_tool(
            "summarize_hours", {"start_date": "2026-08-07", "end_date": "2026-08-03"}
        )
        results.append(False)
    except Exception as error:
        results.append("以前の日付" in str(error))

    print(f"{sum(results)}/{len(results)} PASS")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
