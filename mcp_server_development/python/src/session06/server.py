"""チーム稼働ダッシュボード（Python / セッション6 版）― stdio エントリーポイント

実行： docker compose exec python python src/session06/server.py
（単体で起動すると stderr に 1 行出したあと沈黙します。それが正常です）

stdout は JSON-RPC の通信路そのものなので print() では書きません。
"""

import sys

from create_server import create_dashboard_server

if __name__ == "__main__":
    print("[team-dashboard] stdio でリクエストを待機しています", file=sys.stderr)
    create_dashboard_server().run(transport="stdio")
