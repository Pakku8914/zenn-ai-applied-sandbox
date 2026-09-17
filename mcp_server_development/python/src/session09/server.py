"""セッション9 のサーバー（Python 版）― stdio エントリーポイント

    docker compose exec python python src/session09/server.py

stdout は JSON-RPC の通信路そのものなので print() では書きません。
"""

import os
import sys
from pathlib import Path

from create_server import create_session09_server

DEFAULT_DOCS_ROOT = "src/mid01/docs"


def resolve_docs_root(argv: list[str]) -> Path:
    if len(argv) > 1 and argv[1]:
        return Path(argv[1]).resolve()
    from_env = os.environ.get("DOCSEARCH_ROOT")
    if from_env:
        return Path(from_env).resolve()
    return Path(DEFAULT_DOCS_ROOT).resolve()


if __name__ == "__main__":
    root = resolve_docs_root(sys.argv)
    print(f"[session09] stdio で待機しています（docsRoot={root}）", file=sys.stderr)
    create_session09_server(root).run(transport="stdio")
