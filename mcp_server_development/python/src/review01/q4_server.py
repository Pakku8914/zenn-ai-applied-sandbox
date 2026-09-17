"""日次ダッシュボードサーバー（Python 版）― stdio トランスポートのエントリーポイント

このファイルの仕事は「サーバー定義を stdio につなぐ」ことだけです。

重要：stdio では標準出力（stdout）が JSON-RPC の通信路そのものです。
print() を 1 回でも呼ぶと電文が壊れます。ログは必ず stderr へ。

  docker compose exec python python src/review01/q4_server.py
"""

import sys

from q4_create_server import mcp

if __name__ == "__main__":
    # mcp.run() はここでブロックして戻ってこないので、ログは run の前に出す
    print("[team-dashboard-daily] stdio でリクエストを待機しています", file=sys.stderr)
    mcp.run(transport="stdio")
