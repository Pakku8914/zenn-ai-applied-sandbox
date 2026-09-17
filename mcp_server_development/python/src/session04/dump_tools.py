"""tools/list の中身を JSON で書き出す（Inspector の CLI モード相当）

  docker compose exec -T python python src/session04/dump_tools.py
  docker compose exec -T python python src/session04/dump_tools.py src/session04/pydantic_args.py

このスクリプトはクライアント側なので print を使ってかまいません
（通信路として stdout を使うのはサーバープロセスのほうだけです）。
"""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    entry = sys.argv[1] if len(sys.argv) > 1 else "src/session04/server.py"
    params = StdioServerParameters(command="python", args=[entry])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    # by_alias=True で「電文に出るキー名」（inputSchema など camelCase）に戻す。
    # exclude_none=True で未使用のフィールドを落とし、sort_keys=True で並びを固定して
    # 2 言語の出力を比較しやすくする
    payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
