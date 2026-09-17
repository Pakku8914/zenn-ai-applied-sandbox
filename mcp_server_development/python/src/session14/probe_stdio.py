"""展開した配布物から Python 版サーバーを起動し、MCP で応答するかを確認する

  docker compose exec python python src/session14/probe_stdio.py \
      /tmp/verify/docsearch_mcp-0.1.0/src /app/src/session14/sample-docs

クライアント側のスクリプトなので print を使ってかまいません。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(package_src: Path, docs_root: Path) -> None:
    # 環境変数は自動で子プロセスに渡りません。ホストが渡すのと同じように、
    # 必要なものだけを明示します。これが「配布時の設定項目」の実体です。
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
        "PYTHONPATH": str(package_src),
        "DOCSEARCH_ROOT": str(docs_root),
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "docsearch_mcp"],
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"[probe] serverInfo: {init.server_info.name} v{init.server_info.version}")

            tools = (await session.list_tools()).tools
            print(f"[probe] tools: {', '.join(tool.name for tool in tools)}")

            result = await session.call_tool("search_documents", {"query": "VPN"})
            structured = result.structured_content or {}
            hits = structured.get("results") or []
            first = hits[0]["path"] if hits else None
            print(
                f'[probe] search_documents("VPN"): '
                f'totalMatched={structured.get("totalMatched")} / 先頭={first}'
            )

    print("OK: 展開した配布物から起動したサーバーが MCP として応答しました")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "使い方: python src/session14/probe_stdio.py <展開先の src> <検索対象ディレクトリ>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    anyio.run(main, Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
