"""stdio エントリーポイントの非同期版（run_stdio_async を直接使う）

  docker compose exec python python src/session04/server_async.py
"""

import asyncio
import sys

from create_server import mcp


async def main() -> None:
    # ここに「サーバーを起こす前に済ませたい非同期の準備」を書ける
    # 例：DB コネクションプールの作成、外部 API のトークン取得
    print("[team-dashboard] stdio でリクエストを待機しています", file=sys.stderr)
    await mcp.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
