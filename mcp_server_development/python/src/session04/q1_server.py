"""問題1: 3 ツール構成の stdio エントリーポイント

import の順序に意味があります。
q1_create_server を先に読み込むことで list_projects が登録され、
そのあとに取り出す mcp には 3 ツールが載っています。
"""

import sys

import q1_create_server  # noqa: F401  デコレータの副作用でツールを登録するための import
from create_server import mcp

if __name__ == "__main__":
    print("[team-dashboard] stdio でリクエストを待機しています", file=sys.stderr)
    mcp.run(transport="stdio")
