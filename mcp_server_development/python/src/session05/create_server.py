"""チーム稼働ダッシュボード ― サーバー定義（Python / セッション5 版）

本章で新しく学ぶ 3 ツールに絞っています。
  - list_members   : 戻り値の型注釈から outputSchema が生成される
  - archive_project: 破壊的操作の注釈と、例外による isError
  - export_report  : resource_link と埋め込みリソースの出し分け

Python 固有の要点が 3 つあります。
  ① ツール名は関数名になる。契約なので name= で明示する
  ② ツールの引数名は仮引数の名前そのもの。Field(alias=...) では変えられないので
     電文の引数名を snake_case にする（TypeScript 版とは名前が食い違います）
  ③ mcp 2.0 のモデルのフィールドは snake_case（read_only_hint / mime_type）
"""

from __future__ import annotations

import sys
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import (
    ContentBlock,
    EmbeddedResource,
    ResourceLink,
    TextContent,
    TextResourceContents,
    ToolAnnotations,
)
from pydantic import BaseModel, Field

import data

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
PROJECT_ID_PATTERN = r"^p-[a-z-]{2,32}$"

#: 読み取り専用ツールに付ける注釈（destructive / idempotent は意味を持たないので書かない）
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

#: 破壊的操作に付ける注釈（4 つすべてを明示する）
DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)


class MemberOut(BaseModel):
    """list_members が返す 1 件分。

    フィールド名はプロトコルに出るキーそのものなので、TypeScript 版に合わせて
    camelCase で書いています（エイリアスを使う方法もありますが、SDK が by_alias を
    どう扱うかに依存するため、キー名を直接書くのが最も確実です）。
    """

    memberId: str = Field(description="メンバー ID")
    name: str = Field(description="氏名")
    team: str = Field(description="所属チーム（platform / data）")
    weeklyCapacityHours: float = Field(description="週の稼働可能時間")


class MemberListOut(BaseModel):
    count: int = Field(description="返したメンバーの件数")
    members: list[MemberOut] = Field(description="メンバーの一覧（メンバー ID の昇順）")


class ArchiveResultOut(BaseModel):
    projectId: str
    name: str = Field(description="プロジェクト名")
    alreadyArchived: bool = Field(description="呼び出し前からアーカイブ済みだったか")
    archivedAt: str = Field(description="アーカイブした日時（ISO 8601）")
    affectedWorkLogs: int = Field(description="紐づく稼働記録の件数（削除はしません）")
    affectedHours: float = Field(description="紐づく稼働記録の合計時間")
    remainingActiveProjects: list[str] = Field(description="残っているプロジェクトの ID")


def create_dashboard_server() -> MCPServer:
    mcp = MCPServer(name="team-dashboard", version="0.2.0")

    @mcp.tool(name="list_members", title="メンバー一覧", annotations=READ_ONLY)
    def list_members_tool(team: Literal["platform", "data"] | None = None) -> MemberListOut:
        """チームに所属するメンバーの一覧を返します。

        稼働時間を集計する前に、有効なメンバー ID を確認する用途で使ってください。

        Args:
            team: 特定のチームだけに絞る場合に指定します。省略すると全員を返します
        """
        found = data.list_members(team)
        return MemberListOut(
            count=len(found),
            members=[
                MemberOut(
                    memberId=member.id,
                    name=member.name,
                    team=member.team,
                    weeklyCapacityHours=member.weekly_capacity_hours,
                )
                for member in found
            ],
        )

    @mcp.tool(name="archive_project", title="プロジェクトのアーカイブ", annotations=DESTRUCTIVE)
    def archive_project_tool(
        # 仮引数の名前がそのまま電文の引数名になります（alias では変えられません）
        project_id: Annotated[
            str,
            Field(
                pattern=PROJECT_ID_PATTERN,
                description="アーカイブするプロジェクトの ID（例: p-search）",
            ),
        ],
        reason: Annotated[
            str,
            Field(
                min_length=3,
                max_length=200,
                description="アーカイブする理由。監査ログに記録されます（3〜200 文字）",
            ),
        ],
    ) -> ArchiveResultOut:
        """指定したプロジェクトをアーカイブします。

        稼働記録そのものは削除しません。すでにアーカイブ済みの場合も成功として扱います。
        元に戻すツールは用意していないため、ユーザーから明示的に依頼された場合だけ
        呼び出してください。
        """
        if data.find_project(project_id) is None:
            active = ", ".join(project.id for project in data.list_active_projects())
            # 例外のメッセージがそのままツール結果（isError: true）の本文になります。
            # だからこそ内部情報を混ぜず、AI が回復できる文面にします。
            raise ValueError(f"プロジェクト ID {project_id} は存在しません。有効な ID: {active}")

        # 監査ログは stderr へ。stdout は JSON-RPC の通信路なので print してはいけない
        print(f"[audit] archive_project projectId={project_id} reason={reason}", file=sys.stderr)
        return ArchiveResultOut(**data.archive_project(project_id))

    @mcp.tool(
        name="export_report", title="稼働レポートの書き出し（CSV）", annotations=READ_ONLY
    )
    def export_report_tool(
        # TypeScript 版は from / to ですが、Python では仮引数名がそのまま電文に出るため
        # セッション4 と同じ start_date / end_date に揃えます
        start_date: Annotated[
            str,
            Field(
                pattern=DATE_PATTERN,
                description="書き出す期間の開始日（YYYY-MM-DD、この日を含む）",
            ),
        ],
        end_date: Annotated[
            str,
            Field(
                pattern=DATE_PATTERN,
                description="書き出す期間の終了日（YYYY-MM-DD、この日を含む）",
            ),
        ],
        inline: Annotated[
            bool,
            Field(description="true にすると CSV 本文を埋め込みます（2048 バイトまで）"),
        ] = False,
    ) -> list[ContentBlock]:
        """指定期間の稼働記録を CSV にし、リソースへの参照（resource_link）を返します。

        CSV の本文はレスポンスに含めません。中身が必要な場合は返された URI を
        読み取ってください。inline に true を指定すると本文を埋め込みますが、
        上限を超える場合は自動的に参照に切り替わります。
        """
        try:
            span = data.days_between(start_date, end_date)
        except ValueError as exc:
            # 例外の英語メッセージをそのまま漏らさない（情報漏えいの防止）
            raise ValueError(
                "start_date / end_date には実在する日付を指定してください（例: 2026-08-03）。"
            ) from exc
        if span <= 0:
            raise ValueError(
                f"start_date（{start_date}）は end_date（{end_date}）以前の日付を指定してください。"
            )
        if span > data.MAX_RANGE_DAYS:
            raise ValueError(
                f"書き出せる期間は最長 {data.MAX_RANGE_DAYS} 日です（指定された期間は {span} 日）。"
            )

        rows = data.build_report_rows(start_date, end_date)
        csv = data.to_csv(rows)
        size = data.byte_size_of(csv)
        total_hours = data.sum_hours(rows)
        uri = f"report://weekly/{start_date}_{end_date}.csv"
        embed = inline and size <= data.MAX_INLINE_BYTES

        if embed:
            summary = (
                f"{start_date} 〜 {end_date} の稼働記録 {len(rows)} 件"
                f"（合計 {total_hours} 時間）を CSV にしました。"
                "本文はこのレスポンスに含まれています。"
            )
            body: ContentBlock = EmbeddedResource(
                type="resource",
                resource=TextResourceContents(uri=uri, mime_type="text/csv", text=csv),
            )
        else:
            summary = (
                f"{start_date} 〜 {end_date} の稼働記録 {len(rows)} 件"
                f"（合計 {total_hours} 時間）を CSV にしました。"
                f"本文（{size} バイト）は {uri} を読み取ってください。"
            )
            body = ResourceLink(
                type="resource_link",
                uri=uri,
                name=f"{start_date}_{end_date}.csv",
                title="週次稼働レポート（CSV）",
                mime_type="text/csv",
                description=(
                    f"{start_date} 〜 {end_date} の稼働記録 {len(rows)} 件（{size} バイト）"
                ),
            )

        return [TextContent(type="text", text=summary), body]

    return mcp
