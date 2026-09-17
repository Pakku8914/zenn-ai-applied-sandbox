"""問題4（後半）: 同じ機能を「引数 1 個（Pydantic モデル）」で受ける版

電文がどう変わるかを見るための比較用です。本番ではフラット版を公開します。
モデルのフィールドでは alias が機能するので、セッション3 と同じ from / to を
電文に残せます（代わりに引数が入れ子になります）。

  docker compose exec -T python python src/session04/dump_tools.py src/session04/q4_nested.py
"""

import sys
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

import data
from create_server import DATE_PATTERN, ToolFailure, format_summary
from q4_create_server import GroupBy, format_project_summary

mcp = MCPServer(name="team-dashboard-nested", version="0.1.0")


class HoursQuery(BaseModel):
    """稼働時間の集計条件"""

    # 電文（alias）側でも Python 側の名前でも埋められるようにする
    model_config = ConfigDict(populate_by_name=True)

    date_from: Annotated[
        str,
        Field(alias="from", pattern=DATE_PATTERN, description="集計期間の開始日（YYYY-MM-DD、この日を含む）"),
    ]
    date_to: Annotated[
        str,
        Field(alias="to", pattern=DATE_PATTERN, description="集計期間の終了日（YYYY-MM-DD、この日を含む）"),
    ]
    # ここは alias を付けず、フラット版と同じ名前にしておく
    group_by: Annotated[
        GroupBy | None,
        Field(description="集計の切り口。省略するとメンバー別になります。"),
    ] = None


@mcp.tool(title="稼働時間の集計", structured_output=False)
def summarize_hours(query: HoursQuery) -> str:
    """指定した期間の稼働時間を集計し、合計と内訳を返します。条件は query オブジェクトにまとめて渡してください。"""
    span = data.days_between(query.date_from, query.date_to)
    if span is None or span <= 0:
        raise ToolFailure("from / to には実在する日付を、from が to 以前になるように指定してください。")

    if (query.group_by or "member") == "project":
        return format_project_summary(query.date_from, query.date_to)
    return format_summary(data.summarize_hours(query.date_from, query.date_to))


if __name__ == "__main__":
    print("[team-dashboard-nested] stdio でリクエストを待機しています", file=sys.stderr)
    mcp.run(transport="stdio")
