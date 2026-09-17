"""問題6 の解答：stdio エントリーポイント"""

import sys

from q6_create_server import create_summary_server

if __name__ == "__main__":
    print("[team-dashboard-q6] stdio でリクエストを待機しています", file=sys.stderr)
    create_summary_server().run(transport="stdio")
