"""OAuth 風のトークン検証を入れた Python 版 MCP サーバー（Streamable HTTP）

起動:
  docker compose exec -d -e MCP_SHARED_SECRET=demo-shared-secret-0123456789abcdef python \
    sh -c 'python src/session12/serve_protected.py > /tmp/protected.log 2>&1'
停止:
  docker compose exec python sh -c 'kill $(cat /tmp/mcp-protected-py.pid)'
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

from auth_middleware import BearerAuthMiddleware
from tokens import load_shared_secret

# mid01 のモジュールを書き換えずに再利用する（セッション7 と同じ手当て）
MID01_DIR = Path(__file__).resolve().parent.parent / "mid01"
sys.path.insert(0, str(MID01_DIR))

from create_server import create_docsearch_server  # noqa: E402

HOST = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_HTTP_PORT", "8787"))
ISSUER = os.environ.get("MCP_AS_ISSUER", "http://127.0.0.1:9100")
RESOURCE = os.environ.get("MCP_RESOURCE", f"http://{HOST}:{PORT}/mcp")
DOCS_ROOT = Path(os.environ.get("DOCSEARCH_ROOT", "src/mid01/docs")).resolve()
PID_FILE = Path("/tmp/mcp-protected-py.pid")


def build_asgi_app(mcp: object) -> object:
    """★ ASGI アプリの取り出し方は SDK の版で変わるので、候補を順に試す。
    どれも無い場合は、下の確認コマンドで手元のメソッド名を調べてください。"""
    for name in ("streamable_http_app", "http_app", "asgi_app"):
        factory = getattr(mcp, name, None)
        if callable(factory):
            print(f"[docsearch-http] ASGI アプリの取得に {name}() を使います", file=sys.stderr)
            return factory()
    raise SystemExit(
        "ASGI アプリを取り出すメソッドが見つかりません。"
        "python -c \"from mcp.server.mcpserver import MCPServer; print([n for n in dir(MCPServer) if 'app' in n])\" で確認してください。"
    )


def main() -> None:
    secret = load_shared_secret()
    mcp = create_docsearch_server(DOCS_ROOT)
    app = BearerAuthMiddleware(
        build_asgi_app(mcp),  # type: ignore[arg-type]
        secret=secret,
        issuer=ISSUER,
        audience=RESOURCE,
    )
    PID_FILE.write_text(f"{os.getpid()}\n", encoding="utf-8")
    print(f"[docsearch-http] http://{HOST}:{PORT}/mcp（resource={RESOURCE}）", file=sys.stderr)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
