"""問題6 の解答：確認用クライアント

実行： docker compose exec python python src/session05/answers/q6_verify.py
"""

from __future__ import annotations

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(
        command="python", args=["src/session05/answers/q6_server.py"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool = (await session.list_tools()).tools[0]
            print(f"[1/3] 引数名: {', '.join(sorted((tool.input_schema.get('properties') or {}).keys()))}")

            result = await session.call_tool(
                "summarize_hours", {"start_date": "2026-08-03", "end_date": "2026-08-07"}
            )
            # 失敗は例外ではなく is_error=True の結果で返るので、必ず確認する
            if result.is_error:
                raise RuntimeError(getattr(result.content[0], "text", "呼び出しに失敗しました"))
            payload = result.structured_content or {}
            m002 = next(row for row in payload["members"] if row["memberId"] == "m-002")
            print(
                f"[2/3] 集計: totalHours={payload['totalHours']} "
                f"/ memberCount={payload['memberCount']} / m-002={m002['totalHours']}"
            )

            too_long = await session.call_tool(
                "summarize_hours", {"start_date": "2026-01-01", "end_date": "2026-08-05"}
            )
            print(f"[3/3] 期間超過: isError={too_long.is_error}")


if __name__ == "__main__":
    anyio.run(main)
