"""sampling / roots / elicitation の API 名を自分の環境で確認する

    docker compose exec python python src/session09/inspect_api.py

本章のコードはこの出力に出た名前を使っています。名前が違っていたら
読み替えてください（呼び出しは create_server.py の 3 か所だけです）。
"""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.session import ServerSession

KEYWORDS = ("message", "root", "elicit", "client_params")


def names(target: type) -> list[str]:
    return sorted(
        name
        for name in dir(target)
        if not name.startswith("__") and any(word in name for word in KEYWORDS)
    )


print(f"MCPServer      : {MCPServer.__module__}.{MCPServer.__name__}")
print(f"Context        : {names(Context)}")
print(f"ServerSession  : {names(ServerSession)}")
