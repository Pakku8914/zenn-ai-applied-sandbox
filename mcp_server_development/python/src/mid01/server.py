"""社内ドキュメント検索（Python 版）― stdio エントリーポイント

実行：
  docker compose exec python python src/mid01/server.py
  docker compose exec python python src/mid01/server.py /tmp/mid01-docs

stdout は JSON-RPC の通信路そのものなので print() では書きません。
"""

import os
import sys
from pathlib import Path

from create_server import create_docsearch_server

DEFAULT_DOCS_ROOT = "src/mid01/docs"


def resolve_docs_root(argv: list[str]) -> Path:
    """① コマンドライン第 1 引数 → ② 環境変数 → ③ 既定値 の順で決める"""
    if len(argv) > 1 and argv[1]:
        return Path(argv[1]).resolve()
    from_env = os.environ.get("DOCSEARCH_ROOT")
    if from_env:
        return Path(from_env).resolve()
    return Path(DEFAULT_DOCS_ROOT).resolve()


if __name__ == "__main__":
    root = resolve_docs_root(sys.argv)
    print(f"[docsearch] stdio でリクエストを待機しています（docsRoot={root}）", file=sys.stderr)
    create_docsearch_server(root).run(transport="stdio")
