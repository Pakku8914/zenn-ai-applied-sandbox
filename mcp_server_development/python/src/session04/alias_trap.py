"""実験: フラットな引数に Field(alias=...) を付けると呼び出せないことを確かめる

tools/list には from / to が出るのに、tools/call がどちらの名前でも失敗します。
最後に「動く回避策」（Pydantic モデルで受ける版）も同じ条件で試します。

  docker compose exec python python src/session04/alias_trap.py
"""

import asyncio
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

mcp = MCPServer(name="alias-trap", version="0.1.0")


@mcp.tool(structured_output=False)
def flat_with_alias(
    date_from: Annotated[str, Field(alias="from")],
    date_to: Annotated[str, Field(alias="to")],
) -> str:
    """フラットな引数に alias を付けた版（これが動きません）"""
    return f"{date_from} 〜 {date_to}"


class Range(BaseModel):
    # populate_by_name=True は「Python 側の名前でも埋められる」ことを許す指定。
    # SDK は alias 側で検証するので必須ではありませんが、
    # 同じモデルを自分のコードから組み立てるときに効きます
    model_config = ConfigDict(populate_by_name=True)

    date_from: Annotated[str, Field(alias="from")]
    date_to: Annotated[str, Field(alias="to")]


@mcp.tool(structured_output=False)
def with_model(period: Range) -> str:
    """モデルを 1 引数で受ける版（これは動きます）"""
    return f"{period.date_from} 〜 {period.date_to}"


def schema_of(tools: list, name: str) -> dict:
    # mcp 2.0 の Tool オブジェクトの属性は snake_case です（tool.inputSchema ではありません）
    tool = next(tool for tool in tools if tool.name == name)
    return tool.input_schema


async def main() -> None:
    tools = await mcp.list_tools()

    flat = schema_of(tools, "flat_with_alias")
    print(f"[1] alias 版のスキーマ: properties={list(flat['properties'])} / required={flat['required']}")

    # 2) 電文どおりの名前で呼ぶ
    try:
        await mcp.call_tool("flat_with_alias", {"from": "2026-08-03", "to": "2026-08-07"})
        print("[2] 電文どおりの名前で呼ぶ: 成功")
    except Exception as error:
        print(f"[2] 電文どおりの名前で呼ぶ: 失敗（{type(error).__name__}）: {error}")

    # 3) Python 側の名前で呼ぶ
    try:
        await mcp.call_tool("flat_with_alias", {"date_from": "2026-08-03", "date_to": "2026-08-07"})
        print("[3] Python 側の名前で呼ぶ: 成功")
    except Exception as error:
        print(f"[3] Python 側の名前で呼ぶ: 失敗（'Field required' を含む: {'Field required' in str(error)}）")

    nested = schema_of(tools, "with_model")
    print(f"[4] モデル版のスキーマ: properties={list(nested['properties'])} / $defs={list(nested['$defs'])}")

    # 5) 入れ子にすれば電文の名前を維持できる
    result = await mcp.call_tool(
        "with_model", {"period": {"from": "2026-08-03", "to": "2026-08-07"}}
    )
    print(f"[5] モデル版を呼ぶ: 成功 / {getattr(result.content[0], 'text', '')}")


if __name__ == "__main__":
    asyncio.run(main())
