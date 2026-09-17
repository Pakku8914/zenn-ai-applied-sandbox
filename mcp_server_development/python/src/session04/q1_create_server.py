"""問題1: list_projects を追加する

本文のサーバー定義（create_server.py の mcp）を import して、
デコレータで 3 つ目のツールを足しています。
Python の @mcp.tool() は「import された瞬間に登録する」ので、
このモジュールを読み込むだけでツールが増えます。
"""

from typing import Annotated

from pydantic import Field

import data
from create_server import MemberIdStr, ToolFailure, mcp


@mcp.tool(title="プロジェクト一覧", structured_output=False)
def list_projects(
    # 電文に出る引数名は仮引数の名前そのもの。alias は付けません（本文の第 4 節）
    member_id: Annotated[
        MemberIdStr | None,
        Field(
            description="特定のメンバーが関わっているプロジェクトだけに絞る場合に指定します。省略すると全プロジェクトを返します。",
        ),
    ] = None,
) -> str:
    """稼働記録のあるプロジェクトの一覧（ID・名称）を返します。稼働時間を集計する前に、対象プロジェクトを把握する用途で使ってください。"""
    if member_id is not None and data.find_member(member_id) is None:
        raise ToolFailure(
            f"メンバー ID {member_id} は存在しません。list_members で有効な ID を確認してください。"
        )

    if member_id is None:
        found = list(data.PROJECTS)
    else:
        # そのメンバーの稼働記録に出てくる project_id の集合を作ってから絞り込む
        worked_project_ids = {
            log.project_id for log in data.WORK_LOGS if log.member_id == member_id
        }
        found = [
            project for project in data.PROJECTS if project.id in worked_project_ids
        ]

    found = sorted(found, key=lambda project: project.id)

    if not found:
        return "該当するプロジェクトはありません。"
    lines = [f"- {project.id} {project.name}" for project in found]
    return "\n".join([f"プロジェクト {len(found)} 件", *lines])
