"""サンドボックスの疎通確認スクリプト（Python）

MCP クライアントとして src/server.py を子プロセスで起動し、
  1. initialize ハンドシェイク
  2. tools/list（ツール一覧の取得）
  3. tools/call（ツールの呼び出し）
が成功することを確認します。

実行： docker compose exec python python src/smoke.py
"""

import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(command="python", args=["src/server.py"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            # mcp 2.0 のモデルはフィールド名が snake_case（1.x は serverInfo）
            print(
                f"[1/3] 接続成功: {init.server_info.name} v{init.server_info.version}"
            )

            tools = await session.list_tools()
            print(f"[2/3] tools/list: {', '.join(t.name for t in tools.tools)}")

            result = await session.call_tool("add", {"a": 2, "b": 3})
            first = result.content[0]
            print(f"[3/3] tools/call: {getattr(first, 'text', first)}")

    print("OK: サンドボックスは正常に動作しています")


if __name__ == "__main__":
    asyncio.run(main())
