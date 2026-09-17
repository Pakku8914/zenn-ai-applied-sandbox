"""インメモリでの確認（サーバーを子プロセスとして起動しない）

MCPServer には list_tools() / call_tool() が直接生えています。
トランスポートもクライアントも介さないので、プロセス起動のコストがゼロです。
CI で何百回でも回せます。

  docker compose exec python python src/session04/inmemory_check.py
"""

import asyncio

from create_server import mcp


async def main() -> None:
    # list_tools() が返すのは Tool オブジェクトのリストです
    tools = await mcp.list_tools()
    print("tools:", ", ".join(tool.name for tool in tools))

    result = await mcp.call_tool(
        "summarize_hours", {"start_date": "2026-08-03", "end_date": "2026-08-07"}
    )
    print(getattr(result.content[0], "text", "").splitlines()[0])
    print("is_error:", result.is_error)

    # 直接呼ぶ経路では、ツールの失敗は「例外」として上がってきます（stdio 経由との差）
    try:
        await mcp.call_tool(
            "summarize_hours", {"start_date": "2026-08-07", "end_date": "2026-08-03"}
        )
        print("失敗が返りませんでした（想定外）")
    except Exception as error:
        # 文面の完全一致に依存しない。型名とキーワードだけを見る
        print(
            f"逆順の期間: {type(error).__name__} / "
            f"「以前の日付」を含む: {'以前の日付' in str(error)}"
        )


if __name__ == "__main__":
    asyncio.run(main())
