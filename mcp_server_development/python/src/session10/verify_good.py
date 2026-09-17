"""Python 版の動作確認と、ツール定義サイズの計測

実行： docker compose exec python python src/session10/verify_good.py

クライアント側のスクリプトなので print() を使ってかまいません。
"""

from __future__ import annotations

import json
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def estimate_tokens(text: str) -> int:
    """TypeScript 版（tokens.ts）と同じ近似モデル"""
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    wide_count = len(text) - ascii_count
    return -(-ascii_count // 4) + wide_count


def payload(result: Any) -> dict[str, Any]:
    """structured_content を持つ結果から辞書を取り出す

    mcp 2.0 のモデルは snake_case です（TypeScript SDK の structuredContent に相当）。
    """
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


async def main() -> None:
    params = StdioServerParameters(command="python", args=["src/session10/good_server.py"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            names = sorted(tool.name for tool in tools)
            print(
                f"[1/5] 接続: {init.server_info.name} v{init.server_info.version} "
                f"/ tools={', '.join(names)}"
            )

            found = payload(await session.call_tool("search_requests", {"status": ["in_review"]}))
            ids = ", ".join(item["id"] for item in found["items"])
            print(f"[2/5] search_requests(status=['in_review']): total={found['total']} ids={ids}")

            detail = (await session.call_tool("get_request", {"request_id": "req-1003"})).content[
                0
            ].text
            print(
                f"[3/5] get_request(req-1003): 承認ルート="
                f"{detail.count('（u-9')} 段 / コメント="
                f"{'含まれる' if 'コメント（' in detail else '含まれない'}"
            )

            dry = payload(
                await session.call_tool(
                    "decide_request", {"request_id": "req-1003", "decision": "approve"}
                )
            )
            print(
                f"[4/5] decide_request(ドライラン): applied={dry['applied']} "
                f"{dry['stepLabel']} 確定後={dry['nextStatus']} "
                f"審査終了={'はい' if dry['finalizes'] else 'いいえ'}"
            )

            applied = payload(
                await session.call_tool(
                    "decide_request",
                    {
                        "request_id": "req-1003",
                        "decision": "approve",
                        "confirm": True,
                        "preview_token": dry["previewToken"],
                    },
                )
            )
            print(
                f"[5/5] decide_request(確定): applied={applied['applied']} "
                f"{applied['stepLabel']} 状態={applied['status']}"
            )

            total_chars = 0
            total_tokens = 0
            for tool in sorted(tools, key=lambda t: t.name):
                text = json.dumps(
                    tool.model_dump(mode="json", exclude_none=True),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                total_chars += len(text)
                total_tokens += estimate_tokens(text)
                print(f"  {tool.name:<20}{len(text):>8}{estimate_tokens(text):>9}")
            print(f"[定義サイズ] {len(tools)} 本 / {total_chars} chars / 約 {total_tokens} tokens")
            print("OK: Python 版の 3 ツールが動作しました")


if __name__ == "__main__":
    anyio.run(main)
