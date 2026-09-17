"""チーム稼働ダッシュボード ― サーバー定義（MCPServer インスタンス）

ここではトランスポート（通信路）への接続を行いません。
「何を提供するサーバーか」だけを組み立てます。
つなぎ先は server.py（stdio）や検証スクリプト（インメモリ）が決めます。

セッション3 の node/src/session03/create-server.ts と同じ 2 ツールを公開します。
ツール名・description・出力テキストは TypeScript 版と 1 文字も変えていません
（クライアントから見た契約なので、実装言語で変えたくない部分です）。

ただし summarize_hours の引数名だけは前章と違います（from → start_date）。
理由は本文の第 4 節で実験して確かめます。ここでは「予約語 from は
Python のフラットな引数として受け取れない」という結果だけ先取りしています。
"""

import logging
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

import data

# YYYY-MM-DD の形だけを検査する正規表現（実在する日付かどうかは別に確認します）
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# メンバー ID の形
MEMBER_ID_PATTERN = r"^m-\d{3}$"

# 選択肢を閉じた型。TypeScript 版の z.enum(["platform", "data"]) に相当します
TeamName = Literal["platform", "data"]

# 「形式の制約を持つ文字列」を型として名前を付けておく。任意引数に使い回すためです
MemberIdStr = Annotated[str, Field(pattern=MEMBER_ID_PATTERN)]

# ログは stderr に出す。logging の既定の出力先は stderr なので stdio を汚しません
logger = logging.getLogger(__name__)

mcp = MCPServer(name="team-dashboard", version="0.1.0")


class ToolFailure(Exception):
    """業務ルール上ありえない入力を表す例外。

    SDK がこの例外を捕まえて isError: true のツール結果に変換します。
    TypeScript 版で `{ content: [...], isError: true }` を return していたのと
    同じ意味になります（この差は第 6 節の対応表で整理します）。
    """


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
    # description を明示すると docstring より優先されます。
    # ここでは MAX_RANGE_DAYS の値を文章に埋め込みたいので明示しています
    # （docstring は静的な文字列なので値を差し込めません）。
    description=(
        "指定した期間の稼働時間をメンバー別に集計し、合計と内訳を返します。"
        "期間は開始日・終了日の両方を含みます。"
        f"1 回で集計できるのは最長 {data.MAX_RANGE_DAYS} 日です。"
    ),
    structured_output=False,
)
def summarize_hours(
    # 仮引数の名前が、そのまま電文に出る引数名になります（第 4 節）。
    # だから予約語（from）も camelCase（memberId）もここでは選べません
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
) -> str:
    """期間内の稼働時間を集計する（AI 向けの説明文はデコレータの description= 側に書いています）。"""
    # 形式は Pydantic が保証済み。ここでは「形式は正しいが業務的にありえない入力」を弾く
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

    try:
        # データ層の引数名は date_from / date_to のまま（MCP を知らない層なので
        # 電文の名前に合わせる必要がありません）。位置引数で渡します
        summary = data.summarize_hours(start_date, end_date, member_id)
    except Exception:
        # 内部の例外メッセージを AI に渡さない。詳細はログ（stderr）にだけ残す
        logger.exception("集計に失敗しました")
        raise ToolFailure(
            "集計に失敗しました。期間を短くして再試行してください。"
        ) from None

    return format_summary(summary)


def format_members(found: list[data.Member]) -> str:
    if not found:
        return "該当するメンバーはいません。"
    lines = [
        f"- {member.id} {member.name}（{member.team} / 週 {member.weekly_capacity_hours} 時間）"
        for member in found
    ]
    return "\n".join([f"メンバー {len(found)} 名", *lines])


def format_summary(summary: data.HoursSummary) -> str:
    header = (
        f"{summary.date_from} 〜 {summary.date_to} の稼働時間: "
        f"合計 {data.format_hours(summary.total_hours)} 時間 / "
        f"対象 {len(summary.members)} 名"
    )
    if not summary.members:
        return f"{header}\n対象期間に稼働記録はありません。"
    lines = [
        f"- {row.name}（{row.member_id} / {row.team}）: "
        f"{data.format_hours(row.total_hours)} 時間 / {row.worked_days} 日"
        for row in summary.members
    ]
    return "\n".join([header, *lines])
