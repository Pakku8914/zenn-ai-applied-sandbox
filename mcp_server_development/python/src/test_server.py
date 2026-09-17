"""MCP サーバーのテスト例（Python / インメモリトランスポート）

子プロセスを起動せず、クライアントとサーバーをメモリ上で直結して検証します。
起動コストがゼロなので、CI で何百回でも回せます。

実行： docker compose exec python python -m pytest -q
"""

import pytest
from mcp import Client

from server import mcp


@pytest.mark.asyncio
async def test_list_tools_exposes_add() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert "add" in [t.name for t in tools.tools]


@pytest.mark.asyncio
async def test_call_tool_returns_sum() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})
        assert getattr(result.content[0], "text", None) == "2.0 + 3.0 = 5.0"
