"""チーム稼働ダッシュボード ― サーバー定義（Python / セッション6 版）

Python 固有の要点が 5 つあります。
  ① リソースは @mcp.resource("uri") デコレータ。URI に {変数} を書くとテンプレートになる
  ② テンプレート変数は関数の引数名と一致させる（一致しないと登録時にエラー）
  ③ 補完は @mcp.completion() で 1 つのハンドラにまとめる（TypeScript は変数ごとに関数）
  ④ 購読の受け付けは高水準 API に無い（節の最後で扱います）
  ⑤ ツールの引数名は仮引数の名前そのもの。Field(alias=...) では変えられないので
     snake_case にする（TypeScript 版の memberId / projectId とは一致しません）

この節の API 名（@mcp.resource / @mcp.completion / @mcp.prompt）は SDK の版で
変わりうる箇所です。15 節の確認コマンドで自分の環境の名前を確かめてください。
"""

from __future__ import annotations

import json
import sys
from typing import Annotated, Any, Literal

from mcp.server.mcpserver.prompts.base import UserMessage
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import (
    Completion,
    EmbeddedResource,
    TextContent,
    TextContent,
    TextResourceContents,
    ToolAnnotations,
)
from pydantic import AnyUrl, BaseModel, Field

import data

SUMMARY_URI = "dashboard://summary/current"
GLOSSARY_TEMPLATE = "glossary://{term}"
WEEKLY_TEMPLATE = "report://weekly/{period}.csv"

#: 追加はするが既存データを壊さない、冪等でもないツールの注釈
WRITE_ONLY = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)


class AddWorkLogOut(BaseModel):
    revision: int = Field(description="更新後の集計リソースの改訂番号")
    entries: int = Field(description="登録されている稼働記録の総件数")
    totalHours: float = Field(description="集計リソースの合計稼働時間（更新後）")
    updatedResource: str = Field(description="内容が変わったリソースの URI")


def create_dashboard_server() -> MCPServer:
    mcp = MCPServer(name="team-dashboard", version="0.3.0")

    # ------------------------------------------------------------------
    # 静的リソース
    # ------------------------------------------------------------------
    @mcp.resource(
        SUMMARY_URI,
        name="dashboard_summary",
        description=(
            "チーム全体の稼働時間の集計結果です。"
            f"対象期間は {data.DASHBOARD_FROM} 〜 {data.DASHBOARD_TO} に固定しています。"
        ),
        mime_type="application/json",
    )
    def read_dashboard_summary() -> str:
        # 戻り値が str なら text、bytes なら blob（base64）として送られます
        return json.dumps(data.get_dashboard_snapshot(), ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # リソーステンプレート（変数名 term と引数名 term を一致させる）
    # ------------------------------------------------------------------
    @mcp.resource(
        GLOSSARY_TEMPLATE,
        name="glossary_term",
        description=(
            "社内用語 1 件の定義を Markdown で返します。"
            "term には英小文字・数字・ハイフンからなるスラッグを指定します（例: sprint）。"
        ),
        mime_type="text/markdown",
    )
    def read_glossary_term(term: str) -> str:
        slug = data.normalize_slug(term)
        entry = data.find_term(slug) if slug else None
        if entry is None:
            # リソースの失敗は例外で表します（isError はツールだけの仕組み）。
            # 受け取った値をそのまま返さないのが要点です
            raise ValueError(
                "指定された用語は辞書にありません。"
                f"有効なスラッグ: {', '.join(data.complete_term_slugs(''))}"
            )
        return data.render_term_markdown(entry)

    @mcp.resource(
        WEEKLY_TEMPLATE,
        name="weekly_report_csv",
        description=(
            "指定期間の稼働記録を CSV（UTF-8）で返します。"
            "period は 2026-08-03_2026-08-07 のように「開始日_終了日」で指定します。"
        ),
        mime_type="text/csv",
    )
    def read_weekly_report(period: str) -> str:
        parsed = data.parse_period(period)
        if parsed is None:
            raise ValueError("period は 2026-08-03_2026-08-07 の形式で指定してください。")
        from_date, to_date = parsed
        try:
            span = data.days_between(from_date, to_date)
        except ValueError as exc:
            raise ValueError("period には実在する日付を指定してください。") from exc
        if span <= 0 or span > data.MAX_RANGE_DAYS:
            raise ValueError(f"period の期間は 1〜{data.MAX_RANGE_DAYS} 日にしてください。")
        return data.to_csv(data.build_report_rows(from_date, to_date))

    # ------------------------------------------------------------------
    # 補完（テンプレート変数とプロンプト引数を 1 つのハンドラで処理する）
    # ------------------------------------------------------------------
    @mcp.completion()
    async def complete_argument(ref: Any, argument: Any, context: Any) -> Completion | None:
        """ref.type で「リソーステンプレートの変数」と「プロンプトの引数」を振り分ける。

        クラス名（ResourceTemplateReference など）は仕様改訂で変わった経緯があるため、
        型ではなく ref.type の文字列で判定しています。
        """
        value: str = argument.value or ""

        if ref.type == "ref/resource" and str(ref.uri) == GLOSSARY_TEMPLATE:
            if argument.name == "term":
                return Completion(values=data.complete_term_slugs(value))
            return None

        if ref.type == "ref/prompt" and ref.name == "weekly_report_draft":
            if argument.name == "week_start":
                return Completion(
                    values=[m for m in data.list_week_starts() if m.startswith(value)]
                )
            if argument.name == "week_end":
                # すでに入力済みの引数は context.arguments から取れる
                start = (getattr(context, "arguments", None) or {}).get("week_start")
                candidates = (
                    [data.week_end_of(start)]
                    if start
                    else [data.week_end_of(m) for m in data.list_week_starts()]
                )
                return Completion(values=[c for c in candidates if c.startswith(value)])
        return None

    # ------------------------------------------------------------------
    # プロンプト（引数はすべて文字列。検証はサーバーの責務）
    # ------------------------------------------------------------------
    @mcp.prompt(name="weekly_report_draft", title="週次レポート下書き")
    def weekly_report_draft(
        week_start: str, week_end: str, audience: Literal["team", "manager"] = "team"
    ) -> list[UserMessage]:
        """指定した週の稼働実績から週次レポートの下書きを作る指示と資料を組み立てます。

        Args:
            week_start: 対象週の月曜日（YYYY-MM-DD）
            week_end: 対象週の金曜日（YYYY-MM-DD）
            audience: 読み手（team: チーム内共有 / manager: 上長への報告）
        """
        try:
            span = data.days_between(week_start, week_end)
        except ValueError as exc:
            raise ValueError("week_start / week_end には実在する日付を指定してください。") from exc
        if span <= 0 or span > 31:
            raise ValueError("week_start と week_end は 1〜31 日の範囲にしてください。")

        rows = data.build_report_rows(week_start, week_end)
        csv = data.to_csv(rows)
        snapshot = data.get_dashboard_snapshot()
        uri = f"report://weekly/{week_start}_{week_end}.csv"

        focus = (
            [
                "- 読み手は上長です。所要 1 分で読める要約を先頭に置いてください",
                "- 稼働の偏り（特定メンバーへの集中）とリスクを明示してください",
                "- 数値は合計と前週比だけに絞り、個人名の列挙は避けてください",
            ]
            if audience == "manager"
            else [
                "- 読み手はチームメンバーです。誰が何に時間を使ったかを共有してください",
                "- 来週に持ち越す作業と、手が空きそうな人を書いてください",
                "- 反省ではなく事実の共有として書いてください",
            ]
        )

        instruction = "\n".join(
            [
                f"{week_start}（月）〜 {week_end}（金）の週次レポートの下書きを作成してください。",
                "",
                "## 前提",
                f"- 集計対象の全期間: {snapshot['from']} 〜 {snapshot['to']}（改訂 {snapshot['revision']}）",
                f"- 全期間の合計稼働時間: {snapshot['totalHours']} 時間 / 対象 {snapshot['memberCount']} 名",
                f"- この週の稼働記録: {len(rows)} 件 / 合計 {data.sum_hours(rows)} 時間",
                "",
                "## 書き方",
                *focus,
                "",
                "## 出力形式",
                "見出し「今週のサマリー」「メンバー別の稼働」「来週の予定」の 3 節構成の Markdown。",
                "用語が分からない場合は glossary://{term} リソースを参照してください。",
            ]
        )

        if data.byte_size_of(csv) <= data.MAX_INLINE_BYTES:
            attachment = EmbeddedResource(
                type="resource",
                # mcp 2.0 の TextResourceContents.uri は str（AnyUrl を渡すと検証で落ちる）
                resource=TextResourceContents(uri=uri, mime_type="text/csv", text=csv),
            )
        else:
            attachment = TextContent(
                type="text",
                text=f"明細は大きいため添付していません。{uri} を読み取ってください。",
            )

        return [
            # mcp 2.0 のプロトタイプは mcp.types.PromptMessage ではなく
            # mcp.server.mcpserver.prompts.base の Message 系を期待します。
            # PromptMessage を返すと JSON 文字列として TextContent に押し込まれます
            UserMessage(content=TextContent(type="text", text=instruction)),
            UserMessage(content=attachment),
        ]

    # ------------------------------------------------------------------
    # ツール（更新通知の送信元）
    # ------------------------------------------------------------------
    @mcp.tool(name="add_work_log", title="稼働記録の追加", annotations=WRITE_ONLY)
    async def add_work_log_tool(
        # 仮引数の名前がそのまま電文の引数名になります。
        # Field(alias="memberId") を付けても tools/call は通りません（セッション5 の 12 節）
        member_id: Annotated[
            str,
            Field(pattern=r"^m-\d{3}$", description="記録するメンバーの ID"),
        ],
        project_id: Annotated[
            str,
            Field(pattern=r"^p-[a-z-]{2,32}$", description="プロジェクトの ID"),
        ],
        date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="稼働日")],
        hours: Annotated[float, Field(ge=0.5, le=12, description="稼働時間（0.5〜12 時間）")],
        ctx: Context,
    ) -> AddWorkLogOut:
        """稼働記録を 1 件追加します。

        追加すると集計リソース（dashboard://summary/current）の内容が変わります。
        同じ内容で 2 回呼ぶと 2 件登録されます。
        """
        if data.find_member(member_id) is None:
            raise ValueError(f"メンバー ID {member_id} は存在しません。")
        if data.find_project(project_id) is None:
            raise ValueError(f"プロジェクト ID {project_id} は存在しません。")

        result = data.add_work_log(member_id, project_id, date, hours)

        # 更新通知はセッション経由で送ります。stdout ではなく通信路に乗る通知なので、
        # ログは stderr に出します
        await ctx.session.send_resource_updated(AnyUrl(SUMMARY_URI))
        print(
            f"[notify] resources/updated {SUMMARY_URI} revision={result['revision']}",
            file=sys.stderr,
        )

        return AddWorkLogOut(
            revision=result["revision"],
            entries=result["entries"],
            totalHours=result["totalHours"],
            updatedResource=SUMMARY_URI,
        )

    return mcp
