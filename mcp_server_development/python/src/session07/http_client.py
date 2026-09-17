"""Streamable HTTP でつなぐ検証用クライアント（Python）

  docker compose exec python python src/session07/http_client.py

クライアント側なので print() を使ってかまいません。
"""

from __future__ import annotations

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://127.0.0.1:8787/mcp"


async def main() -> None:
    # 3 つ目の戻り値はセッション ID を取り出す関数（トランスポートが保持している）
    async with streamablehttp_client(URL) as (read, write, get_session_id):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"[1/3] 接続: {init.server_info.name} v{init.server_info.version}")
            print(f"[2/3] Mcp-Session-Id: {get_session_id()}")

            result = await session.call_tool(
                "search_documents", {"query": "VPN", "limit": 2}
            )
            structured = result.structuredContent or {}
            hits = ", ".join(
                f"{hit['path']}({hit['score']})" for hit in structured.get("results", [])
            )
            print(
                f"[3/3] tools/call: totalMatched={structured.get('totalMatched')}"
                f" returned={structured.get('returned')} → {hits}"
            )


if __name__ == "__main__":
    anyio.run(main)
