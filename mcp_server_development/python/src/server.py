"""最小の MCP サーバー（Python / stdio トランスポート）

ツールを 1 つだけ公開します。サンドボックスが正しく動くことを確認するための
「Hello, World」相当のサーバーです。

重要：stdio トランスポートでは標準出力（stdout）が JSON-RPC の通信路そのものです。
print() で何か書くと電文が壊れます。ログは必ず標準エラー出力（stderr）へ。

注意：Python SDK の `mcp` は 2.0 で高水準クラス名が `FastMCP` から `MCPServer` に
変わりました。Web 上の 1.x 向けのサンプル（`from mcp.server.fastmcp import FastMCP`）
はそのままでは動きません。
"""

import sys

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(name="sandbox-server", version="1.0.0")


@mcp.tool()
def add(a: float, b: float) -> str:
    """2 つの数値を足し合わせて結果を返します。

    Args:
        a: 足される数
        b: 足す数
    """
    return f"{a} + {b} = {a + b}"


if __name__ == "__main__":
    # ログは stderr へ。stdout は JSON-RPC 専用なので絶対に汚さない
    print("[sandbox-server] stdio でリクエストを待機しています", file=sys.stderr)
    mcp.run(transport="stdio")
