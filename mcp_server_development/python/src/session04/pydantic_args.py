"""比較用：Pydantic モデルを 1 引数に取るツール（入れ子スキーマの実験）

本文のサーバーとは別の MCPServer インスタンスです。
「まとめて受ける」書き方が電文にどう出るかを見るためのファイルです。
第 4 節の選択肢 (A) ―― 予約語の from / to を電文に残したまま動く唯一の形 ――
を、本章のサーバーに近い規模で書いたものです。

  docker compose exec -T python python src/session04/dump_tools.py src/session04/pydantic_args.py
"""

import sys
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

import data
from create_server import DATE_PATTERN

mcp = MCPServer(name="team-dashboard-nested", version="0.1.0")


class HoursQuery(BaseModel):
    """稼働時間の集計条件"""

    # 電文（alias）側でも Python 側の名前でも埋められるようにする
    model_config = ConfigDict(populate_by_name=True)

    date_from: Annotated[
        str,
        Field(alias="from", pattern=DATE_PATTERN, description="集計期間の開始日（YYYY-MM-DD）"),
    ]
    date_to: Annotated[
        str,
        Field(alias="to", pattern=DATE_PATTERN, description="集計期間の終了日（YYYY-MM-DD）"),
    ]


@mcp.tool(title="稼働時間の集計（入れ子版）", structured_output=False)
def summarize_hours_nested(query: HoursQuery) -> str:
    """集計条件を 1 つのオブジェクトにまとめた版です。入力スキーマが入れ子になります。"""
    summary = data.summarize_hours(query.date_from, query.date_to)
    return (
        f"{summary.date_from} 〜 {summary.date_to} の合計 "
        f"{data.format_hours(summary.total_hours)} 時間"
    )


if __name__ == "__main__":
    print("[team-dashboard-nested] stdio でリクエストを待機しています", file=sys.stderr)
    mcp.run(transport="stdio")
