"""問題2: 修正版の stdio エントリーポイント

修正点は 3 つです（詳細は解説の表）。
  1. import を実行時に解決できる形に直した
  2. ログの出力先を stdout から stderr に変えた
  3. mcp.run(transport="stdio") を呼んで待機状態に入るようにした
"""

import sys

from create_server import mcp

if __name__ == "__main__":
    print("[q2-server] stdio でリクエストを待機しています", file=sys.stderr)
    mcp.run(transport="stdio")
