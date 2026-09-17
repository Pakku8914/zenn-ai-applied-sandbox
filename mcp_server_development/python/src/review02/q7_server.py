"""社内お知らせ掲示板（Python 版）― stdio エントリーポイント

実行： docker compose exec python python src/review02/q7_server.py
（単体で起動すると stderr に 1 行出したあと沈黙します。それが正常です）

stdout は JSON-RPC の通信路そのものなので print() では書きません。
"""

import sys

from q7_create_server import create_notice_server

if __name__ == "__main__":
    print("[notice-board] stdio でリクエストを待機しています", file=sys.stderr)
    create_notice_server().run(transport="stdio")
