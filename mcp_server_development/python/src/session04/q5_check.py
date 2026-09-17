"""問題5: 契約テストの原型となる検証クライアント

本文のサーバーを子プロセスとして起動し、正常系 1 件・異常系 3 件・
一覧 1 件を検証して PASS / FAIL を表示します。
1 つでも FAIL があれば終了コード 1 で終わります（CI に載せられる形）。

  docker compose exec python python src/session04/q5_check.py
"""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult

ENTRY = "src/session04/server.py"


def text_of(result: CallToolResult) -> str:
    first = result.content[0] if result.content else None
    return getattr(first, "text", "")


def report(ok: bool, label: str) -> bool:
    """判定結果を 1 行で表示して、その結果を返す"""
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    return ok


async def main() -> int:
    results: list[bool] = []
    params = StdioServerParameters(command="python", args=[ENTRY])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. tools/list の内容
            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            results.append(
                report(
                    names == ["list_members", "summarize_hours"],
                    f"1. tools/list が {len(names)} 件（{', '.join(names)}）",
                )
            )

            # 2. 正常系
            normal = await session.call_tool(
                "summarize_hours",
                {"start_date": "2026-08-03", "end_date": "2026-08-07"},
            )
            results.append(
                report("合計 56 時間" in text_of(normal), "2. 正常系の集計が 56 時間")
            )

            # 3. 業務エラー（期間が逆順）。例外にはならず、結果に is_error が立つ
            reversed_range = await session.call_tool(
                "summarize_hours",
                {"start_date": "2026-08-07", "end_date": "2026-08-03"},
            )
            results.append(
                report(reversed_range.is_error is True, "3. 期間が逆順なら is_error")
            )

            # 4. 業務エラー（存在しないメンバー ID）
            unknown_member = await session.call_tool(
                "summarize_hours",
                {
                    "start_date": "2026-08-03",
                    "end_date": "2026-08-07",
                    "member_id": "m-999",
                },
            )
            results.append(
                report(
                    unknown_member.is_error is True,
                    "4. 存在しないメンバー ID なら is_error",
                )
            )

            # 5. スキーマ違反。どの層で返るかは SDK の版に依存するので両方を許容する
            try:
                broken = await session.call_tool(
                    "summarize_hours",
                    {"start_date": "2026/08/03", "end_date": "2026-08-07"},
                )
                results.append(
                    report(
                        broken.is_error is True,
                        "5. 日付形式違反は失敗として返る（ツール結果）",
                    )
                )
            except MCPError as error:
                results.append(
                    report(
                        True,
                        f"5. 日付形式違反は失敗として返る（JSON-RPC エラー {error.error.code}）",
                    )
                )

    passed = sum(results)
    print(f"{passed}/{len(results)} PASS")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    # 終了コードは最後に一度だけ設定する。途中で exit すると出力が途切れることがある
    sys.exit(asyncio.run(main()))
