"""チーム稼働ダッシュボードの疎通確認クライアント（Python）

  docker compose exec python python src/session04/smoke.py
  docker compose exec python python src/session04/smoke.py src/session04/q1_server.py

このスクリプトは「クライアント側」なので print を使ってかまいません。
通信路として stdout を使っているのはサーバープロセスのほうだけで、
クライアントの stdout は人間が読む画面にすぎないからです。
"""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult


def text_of(result: CallToolResult) -> str:
    first = result.content[0] if result.content else None
    return getattr(first, "text", "(テキストなし)")


async def main() -> None:
    entry = sys.argv[1] if len(sys.argv) > 1 else "src/session04/server.py"
    # クライアントがサーバーを子プロセスとして起動する。これが stdio トランスポートの実像
    params = StdioServerParameters(command="python", args=[entry])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            # mcp 2.0 のモデルはフィールド名が snake_case（1.x は serverInfo）
            print(f"[1/6] 接続成功: {init.server_info.name} v{init.server_info.version}")

            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            print(f"[2/6] tools/list: {', '.join(names)}")

            print("[3/6] list_members(team=platform):")
            print(text_of(await session.call_tool("list_members", {"team": "platform"})))

            print("[4/6] summarize_hours(2026-08-03 〜 2026-08-07):")
            print(
                text_of(
                    await session.call_tool(
                        "summarize_hours",
                        {"start_date": "2026-08-03", "end_date": "2026-08-07"},
                    )
                )
            )

            # 業務エラー：形式は正しいが期間が逆順。ツール結果として失敗が返る
            reversed_range = await session.call_tool(
                "summarize_hours",
                {"start_date": "2026-08-07", "end_date": "2026-08-03"},
            )
            body = text_of(reversed_range)
            # 文面そのものではなくフラグとキーワードで判定する（理由は本文参照）
            print(
                f"[5/6] 期間が逆順: is_error={reversed_range.is_error} / "
                f"「以前の日付」を含む: {'以前の日付' in body}"
            )

            # スキーマ違反：日付の形式が違う。どの層のエラーになるかを確認する
            try:
                broken = await session.call_tool(
                    "summarize_hours",
                    {"start_date": "2026/08/03", "end_date": "2026-08-07"},
                )
                print(f"[6/6] 日付形式違反: ツール結果で返りました（is_error={broken.is_error}）")
            except MCPError as error:
                print(f"[6/6] 日付形式違反: JSON-RPC エラー code={error.error.code}")

    print("OK: セッション4 のサーバーは TypeScript 版と同じテキストを返しています")


if __name__ == "__main__":
    asyncio.run(main())
