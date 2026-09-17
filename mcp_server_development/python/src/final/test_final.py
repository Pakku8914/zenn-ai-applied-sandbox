"""Python 版のテスト（インメモリ）

  docker compose exec python python -m pytest -q src/final
"""

import sys
from pathlib import Path

import pytest
from mcp import Client

# pytest.ini の pythonpath = src は src までしか追加しないので、自分のディレクトリを足す
sys.path.insert(0, str(Path(__file__).resolve().parent))

from create_server import mcp  # noqa: E402


@pytest.mark.asyncio
async def test_tools_are_two() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert sorted(tool.name for tool in tools.tools) == ["get_request", "search_requests"]


@pytest.mark.asyncio
async def test_argument_names_match_typescript() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        by_name = {tool.name: tool for tool in tools.tools}
        # mcp 2.0 の Tool は snake_case（inputSchema は存在しない）
        properties = by_name["search_requests"].input_schema["properties"]
        # 電文の引数名が TypeScript 版と一致していること
        assert "applicantId" in properties
        assert "minAmountYen" in properties


@pytest.mark.asyncio
async def test_search_counts_match_typescript() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("search_requests", {"status": ["in_review"], "limit": 50})
        assert getattr(result.content[0], "text", "").startswith("6 件中 6 件")


@pytest.mark.asyncio
async def test_unknown_id_is_tool_failure() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_request", {"requestId": "req-9999"})
        assert result.is_error is True
        assert "search_requests" in getattr(result.content[0], "text", "")
