"""問題6 の解答：Python 版 summarize_hours

要点は 3 つです。
  ① 電文の引数名は仮引数の名前そのもの。Field(alias=...) では変えられないので
     本文の Python 版に合わせて start_date / end_date / member_id にする
  ② 出力モデルのフィールド名がそのままプロトコルのキーになる（camelCase で書く）
  ③ 業務エラーは例外を投げる（SDK が isError のツール結果に変換する）

answers/ から 1 つ上の data.py を読むため、sys.path に親ディレクトリを足しています
（本文の create_server.py は同じ階層なのでこの操作は不要でした）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import data  # noqa: E402  （sys.path を設定した後に import する必要があるため）

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
MEMBER_ID_PATTERN = r"^m-\d{3}$"

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


class MemberHoursOut(BaseModel):
    memberId: str = Field(description="メンバー ID")
    name: str = Field(description="氏名")
    team: str = Field(description="所属チーム")
    totalHours: float = Field(description="そのメンバーの合計稼働時間")
    workedDays: int = Field(description="稼働記録があった日数")


class HoursSummaryOut(BaseModel):
    # 出力モデルのフィールド名がそのままプロトコル上のキーになります。
    # from / to は Python の識別子にできないので startDate / endDate にします
    startDate: str = Field(description="集計期間の開始日")
    endDate: str = Field(description="集計期間の終了日")
    totalHours: float = Field(description="期間内の合計稼働時間")
    memberCount: int = Field(description="稼働記録があったメンバーの人数")
    members: list[MemberHoursOut] = Field(description="メンバー別の内訳（メンバー ID の昇順）")


def create_summary_server() -> MCPServer:
    mcp = MCPServer(name="team-dashboard-q6", version="0.2.0")

    @mcp.tool(name="summarize_hours", title="稼働時間の集計", annotations=READ_ONLY)
    def summarize_hours_tool(
        # 仮引数の名前がそのまま電文の引数名になります（alias では変えられません）
        start_date: Annotated[
            str,
            Field(
                pattern=DATE_PATTERN,
                description="集計期間の開始日（YYYY-MM-DD、この日を含む）",
            ),
        ],
        end_date: Annotated[
            str,
            Field(
                pattern=DATE_PATTERN,
                description="集計期間の終了日（YYYY-MM-DD、この日を含む）",
            ),
        ],
        member_id: Annotated[
            str | None,
            Field(
                pattern=MEMBER_ID_PATTERN,
                description="特定のメンバーだけを集計する場合に指定します。省略すると全員が対象です。",
            ),
        ] = None,
    ) -> HoursSummaryOut:
        """指定した期間の稼働時間をメンバー別に集計し、合計と内訳を返します。

        期間は開始日・終了日の両方を含みます。1 回で集計できるのは最長 92 日です。
        """
        try:
            span = data.days_between(start_date, end_date)
        except ValueError as exc:
            raise ValueError(
                "start_date / end_date には実在する日付を指定してください（例: 2026-08-03）。"
            ) from exc
        if span <= 0:
            raise ValueError(
                f"start_date（{start_date}）は end_date（{end_date}）以前の日付を指定してください。"
            )
        if span > data.MAX_RANGE_DAYS:
            raise ValueError(
                f"集計できる期間は最長 {data.MAX_RANGE_DAYS} 日です（指定された期間は {span} 日）。"
                "期間を分けて複数回呼び出してください。"
            )
        if member_id is not None and data.find_member(member_id) is None:
            raise ValueError(
                f"メンバー ID {member_id} は存在しません。list_members で有効な ID を確認してください。"
            )

        return HoursSummaryOut(**data.summarize_hours(start_date, end_date, member_id))

    return mcp
