"""問題4: group_by 対応版の stdio エントリーポイント"""

import sys

from q4_create_server import mcp

if __name__ == "__main__":
    print("[team-dashboard] stdio でリクエストを待機しています", file=sys.stderr)
    mcp.run(transport="stdio")
