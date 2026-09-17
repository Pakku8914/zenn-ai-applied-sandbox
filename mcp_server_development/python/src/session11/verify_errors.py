"""Python 版のエラー設計の観測

実行： docker compose exec python python src/session11/verify_errors.py

クライアント側のスクリプトなので print() を使ってかまいません。

フィールド名（is_error / isError）は SDK の世代で揺れる箇所です
（要件定義の陳腐化リスク #2）。どちらでも読めるヘルパーを置いています。
"""

from __future__ import annotations

import json
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def is_error(result: Any) -> bool:
    """is_error / isError のどちらでも読む"""
    for name in ("is_error", "isError"):
        value = getattr(result, name, None)
        if value is not None:
            return bool(value)
    return False


def structured(result: Any) -> dict[str, Any] | None:
    for name in ("structured_content", "structuredContent"):
        value = getattr(result, name, None)
        if value is not None:
            return value
    return None


def first_text(result: Any) -> str:
    blocks = getattr(result, "content", []) or []
    for block in blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text
    return ""


async def main() -> None:
    params = StdioServerParameters(command="python", args=["src/session11/good_server.py"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            print(
                f"[1/6] 接続: {init.server_info.name} v{init.server_info.version} "
                f"/ tools={', '.join(sorted(tool.name for tool in tools))}"
            )

            detail = await session.call_tool("get_request", {"request_id": "req-1003"})
            text = first_text(detail)
            print(
                f"[2/6] 本文の上限: 切った={'先頭 400 文字だけを返しました' in text} "
                f"文字数={len(text)}"
            )

            with_comments = await session.call_tool(
                "get_request", {"request_id": "req-1003", "include": ["comments"]}
            )
            print(
                f"[3/6] コメントの上限: 直近 5 件="
                f"{'のうち直近 5 件' in first_text(with_comments)}"
            )

            missing = await session.call_tool("get_request", {"request_id": "req-9999"})
            print(
                f"[4/6] 例外を投げた場合: is_error={is_error(missing)} "
                f"文面に code={'[not_found]' in first_text(missing)} "
                f"次の一手={'次の一手:' in first_text(missing)}"
            )

            dry = await session.call_tool(
                "decide_request", {"request_id": "req-1003", "decision": "approve"}
            )
            payload = structured(dry) or json.loads(first_text(dry) or "{}")
            print(
                f"[5/6] 辞書で返した場合: is_error={is_error(dry)} "
                f"applied={payload.get('applied')}"
            )

            bad_state = await session.call_tool(
                "decide_request", {"request_id": "req-1001", "decision": "approve"}
            )
            print(
                f"[6/6] 状態が違う場合: is_error={is_error(bad_state)} "
                f"code={'[invalid_state]' in first_text(bad_state)}"
            )
            print("OK: Python 版のエラー設計を観測しました")


if __name__ == "__main__":
    anyio.run(main)
