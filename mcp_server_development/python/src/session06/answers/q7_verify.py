"""問題7 の確認用クライアント（Python 側）

    docker compose exec python python src/session06/answers/q7_verify.py

TypeScript 側（q7-verify.ts）と同じ 3 項目を出力し、目で突き合わせます。
"""

from __future__ import annotations

import base64
import hashlib

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

URI = "report://excel/2026-08-03_2026-08-07.csv"


async def main() -> None:
    params = StdioServerParameters(
        command="python", args=["src/session06/answers/q7_server.py"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            contents = (await session.read_resource(URI)).contents[0]
            blob: str = contents.blob  # blob のときは text 属性が無い
            digest = hashlib.sha256(blob.encode("ascii")).hexdigest()[:16]
            # デコードして中身も確認する（"utf-16" は BOM を見て自動でエンディアンを判定する）
            text = base64.b64decode(blob).decode("utf-16")
            print(f"[Python] mimeType = {contents.mime_type}")
            print(f"[Python] base64 の長さ = {len(blob)}")
            print(f"[Python] base64 の先頭 4 文字 = {blob[:4]}")
            print(f"[Python] SHA-256（先頭 16 桁） = {digest}")
            print(f"[Python] デコード後の 1 行目 = {text.splitlines()[0]}")
            print(f"[Python] デコード後の行数 = {len(text.rstrip(chr(10)).splitlines())}")


if __name__ == "__main__":
    anyio.run(main)
