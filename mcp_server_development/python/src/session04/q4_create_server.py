"""問題4（前半）: group_by を追加した独立したサーバー定義

本文のインスタンスに足すのではなく、新しい MCPServer を作っています。
summarize_hours を「差し替える」必要があり、同じ名前のツールを
同じインスタンスに 2 回登録することはできないためです。
"""

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

import data
from create_server import (
    DATE_PATTERN,
    MemberIdStr,
    TeamName,
    ToolFailure,
    format_members,
    format_summary,
)

# 集計の切り口。選択肢を閉じておくと AI が別の値を送ってこない
GroupBy = Literal["member", "project"]

mcp = MCPServer(name="team-dashboard", version="0.1.0")


@mcp.tool(title="メンバー一覧", structured_output=False)
def list_members(
    team: Annotated[
        TeamName | None,
        Field(description="特定のチームだけに絞る場合に指定します。省略すると全員を返します。"),
    ] = None,
) -> str:
    """チームに所属するメンバーの一覧（ID・氏名・チーム・週の稼働可能時間）を返します。稼働時間を集計する前に、有効なメンバー ID を確認する用途で使ってください。"""
    return format_members(data.list_members(team))


@mcp.tool(
    title="稼働時間の集計",
    description=(
        "指定した期間の稼働時間を集計し、合計と内訳を返します。"
        "group_by でメンバー別・プロジェクト別を切り替えられます（既定はメンバー別）。"
        "期間は開始日・終了日の両方を含みます。"
        f"1 回で集計できるのは最長 {data.MAX_RANGE_DAYS} 日です。"
    ),
    structured_output=False,
)
def summarize_hours(
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
        MemberIdStr | None,
        Field(
            description="特定のメンバーだけを集計する場合に指定します。省略すると全員が対象です。",
        ),
    ] = None,
    group_by: Annotated[
        GroupBy | None,
        Field(
            description="集計の切り口。member はメンバー別、project はプロジェクト別。省略するとメンバー別になります。",
        ),
    ] = None,
) -> str:
    """（AI 向けの説明文はデコレータの description= 側に書いています）"""
    span = data.days_between(start_date, end_date)
    if span is None:
        raise ToolFailure(
            "start_date / end_date には実在する日付を指定してください（例: 2026-08-03）。"
        )
    if span <= 0:
        raise ToolFailure(
            f"start_date（{start_date}）は end_date（{end_date}）以前の日付を指定してください。"
        )
    if span > data.MAX_RANGE_DAYS:
        raise ToolFailure(
            f"集計できる期間は最長 {data.MAX_RANGE_DAYS} 日です（指定された期間は {span} 日）。"
            "期間を分けて複数回呼び出してください。"
        )
    if member_id is not None and data.find_member(member_id) is None:
        raise ToolFailure(
            f"メンバー ID {member_id} は存在しません。list_members で有効な ID を確認してください。"
        )

    # 既定値はスキーマに書かず、ここで補う（理由は解説の ②）
    mode: GroupBy = group_by if group_by is not None else "member"

    match mode:
        case "member":
            return format_summary(data.summarize_hours(start_date, end_date, member_id))
        case "project":
            return format_project_summary(start_date, end_date, member_id)
        case _:
            # GroupBy に値を足したのに分岐を書き忘れたときだけここに来る
            raise ToolFailure(f"group_by に未対応の値が指定されました: {mode}")


def summarize_by_project(
    date_from: str, date_to: str, member_id: str | None = None
) -> list[tuple[str, str, float, int]]:
    """プロジェクト別の (ID, 名称, 合計時間, 関わった人数) を ID 昇順で返す"""
    targets = [
        log
        for log in data.WORK_LOGS
        if date_from <= log.date <= date_to
        and (member_id is None or log.member_id == member_id)
    ]

    hours_by_project: dict[str, float] = {}
    people_by_project: dict[str, set[str]] = {}
    for log in targets:
        hours_by_project[log.project_id] = (
            hours_by_project.get(log.project_id, 0) + log.hours
        )
        people_by_project.setdefault(log.project_id, set()).add(log.member_id)

    rows: list[tuple[str, str, float, int]] = []
    for project in sorted(data.PROJECTS, key=lambda project: project.id):
        if project.id not in hours_by_project:
            continue
        rows.append(
            (
                project.id,
                project.name,
                data.round_hours(hours_by_project[project.id]),
                len(people_by_project[project.id]),
            )
        )
    return rows


def format_project_summary(
    date_from: str, date_to: str, member_id: str | None = None
) -> str:
    rows = summarize_by_project(date_from, date_to, member_id)
    total = data.round_hours(sum(row[2] for row in rows))
    header = (
        f"{date_from} 〜 {date_to} の稼働時間: "
        f"合計 {data.format_hours(total)} 時間 / 対象 {len(rows)} プロジェクト"
    )
    if not rows:
        return f"{header}\n対象期間に稼働記録はありません。"
    lines = [
        f"- {name}（{project_id}）: {data.format_hours(hours)} 時間 / {people} 名"
        for project_id, name, hours, people in rows
    ]
    return "\n".join([header, *lines])
