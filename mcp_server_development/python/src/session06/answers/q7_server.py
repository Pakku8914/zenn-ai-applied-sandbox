"""問題7 の解答：stdio エントリーポイント"""

import sys

from q7_create_server import create_dashboard_server_q7

if __name__ == "__main__":
    print("[team-dashboard-q7] stdio でリクエストを待機しています", file=sys.stderr)
    create_dashboard_server_q7().run(transport="stdio")
