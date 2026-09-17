"""社内ドキュメント検索（Python 版）― Streamable HTTP エントリーポイント

前面で起動:
  docker compose exec python python src/session07/http_server.py
背面で起動:
  docker compose exec -d python sh -c 'python src/session07/http_server.py > /tmp/http.log 2>&1'
停止:
  docker compose exec python sh -c 'kill $(cat /tmp/mcp-http.pid)'

環境変数
  MCP_HTTP_HOST   待ち受けアドレス（既定 127.0.0.1）
  MCP_HTTP_PORT   待ち受けポート（既定 8787）
  DOCSEARCH_ROOT  検索対象ディレクトリ
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# mid01 のモジュールを書き換えずに再利用する。
# `python src/session07/http_server.py` で起動すると sys.path[0] は src/session07 に
# なるため、兄弟ディレクトリ src/mid01 を明示的に足す必要がある。
MID01_DIR = Path(__file__).resolve().parent.parent / "mid01"
sys.path.insert(0, str(MID01_DIR))

from create_server import create_docsearch_server  # noqa: E402

HOST = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_HTTP_PORT", "8787"))
DOCS_ROOT = Path(os.environ.get("DOCSEARCH_ROOT", "src/mid01/docs")).resolve()
PID_FILE = Path("/tmp/mcp-http.pid")


def main() -> None:
    mcp = create_docsearch_server(DOCS_ROOT)
    PID_FILE.write_text(f"{os.getpid()}\n", encoding="utf-8")
    # HTTP では stdout は通信路ではないが、stdio 版と揃えて stderr に出す
    print(
        f"[docsearch-http] http://{HOST}:{PORT}/mcp で待ち受けています（docsRoot={DOCS_ROOT}）",
        file=sys.stderr,
    )
    # ★ この 1 行だけが SDK の版に依存する（下の確認手順を必ず実行すること）
    mcp.run(transport="http", host=HOST, port=PORT)


if __name__ == "__main__":
    main()
