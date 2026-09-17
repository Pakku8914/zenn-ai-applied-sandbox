"""Python 版の動作確認と、TypeScript 版との差分の洗い出し

  docker compose exec python python src/final/verify_final.py
"""

import asyncio
import json

from create_server import mcp


async def main() -> None:
    tools = await mcp.list_tools()
    print(f"[1] tools: {', '.join(tool.name for tool in tools)}")

    for tool in tools:
        # 属性名は input_schema（snake_case）。TypeScript 版の inputSchema と対応する
        properties = tool.input_schema.get("properties", {})
        print(f"[2] {tool.name} の引数: {', '.join(sorted(properties))}")

    result = await mcp.call_tool("search_requests", {"status": ["in_review"], "limit": 50})
    first_line = getattr(result.content[0], "text", "").splitlines()[0]
    print(f"[3] search(status=in_review): {first_line}")

    for label, args in (
        ("category=expense,min=10000", {"category": "expense", "minAmountYen": 10000}),
        ("applicantId=u-001", {"applicantId": "u-001"}),
        ("query=研修", {"query": "研修"}),
        ("query=購入", {"query": "購入"}),
    ):
        outcome = await mcp.call_tool("search_requests", {**args, "limit": 50})
        head = getattr(outcome.content[0], "text", "").splitlines()[0]
        print(f"[4] search({label}): {head}")

    detail = await mcp.call_tool("get_request", {"requestId": "req-1003", "include": ["comments"]})
    lines = getattr(detail.content[0], "text", "").splitlines()
    print(f"[5] get_request(req-1003): 1行目={lines[0]} / コメント行={lines[-3]}")

    # 直接呼ぶ経路では、ツールの失敗は例外として上がる（stdio 経由との差）
    try:
        await mcp.call_tool("get_request", {"requestId": "req-9999"})
        print("[6] 存在しない ID: 失敗が返りませんでした（想定外）")
    except Exception as error:  # noqa: BLE001 型ではなく文面の一部だけを見る
        print(f"[6] 存在しない ID: {type(error).__name__} / 案内あり={'search_requests' in str(error)}")

    dumped = json.loads(tools[0].model_dump_json())
    extras = [key for key in dumped if key not in {"name", "title", "description", "input_schema"}]
    print(f"[7] Tool の外側にある追加フィールド: {', '.join(sorted(extras))}")


if __name__ == "__main__":
    asyncio.run(main())
