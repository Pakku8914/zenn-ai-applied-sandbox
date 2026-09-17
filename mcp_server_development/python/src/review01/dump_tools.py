"""tools/list の中身を JSON で書き出す（MCP Inspector の CLI モード相当）

  docker compose exec -T python python src/review01/dump_tools.py src/review01/q4_server.py

セッション4 の dump_tools.py と同じ内容です。復習章のファイルだけで完結させるために再掲します。
このスクリプトはクライアント側なので print を使ってかまいません。
"""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    entry = sys.argv[1] if len(sys.argv) > 1 else "src/review01/q4_server.py"
    params = StdioServerParameters(command="python", args=[entry])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    # by_alias=True で「電文に出るキー名」に戻し、sort_keys=True で並びを固定する
    payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
