"""横断復習1 問題4 ― 共通題材（dashboard.ts）の Python 移植（サーバー定義）

TypeScript 版（node/src/review01/dashboard.ts）と電文レベルで一致させることが要件です。
ツール名・引数名・required・description・pattern・enum・正常系の出力テキストは
1 文字も変えていません（クライアントから見た契約なので、実装言語で変えてはいけない部分）。

トランスポートへの接続はこのファイルでは行いません（q4_server.py の責務）。
"""

import datetime
from dataclasses import dataclass
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

# YYYY-MM-DD の形だけを検査する（実在する日付かどうかは別に確認する）
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# 選択肢を閉じた型。TypeScript 版の z.enum(["platform", "data"]) に相当する
TeamName = Literal["platform", "data"]

# 1 回で調べられる期間の上限（日数）。処理量の上限はリソース枯渇対策（詳細はセッション15）
MAX_RANGE_DAYS = 92


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    team: str


@dataclass(frozen=True)
class WorkLog:
    member_id: str
    # YYYY-MM-DD 形式。辞書順の比較がそのまま時系列の比較になる
    date: str
    hours: float


MEMBERS: tuple[Member, ...] = (
    Member("m-001", "佐藤 花子", "platform"),
    Member("m-002", "鈴木 一郎", "platform"),
    Member("m-003", "田中 美咲", "data"),
    Member("m-004", "高橋 健", "data"),
)

WORK_LOGS: tuple[WorkLog, ...] = (
    WorkLog("m-001", "2026-08-03", 5),
    WorkLog("m-002", "2026-08-03", 7.5),
    WorkLog("m-003", "2026-08-03", 6),
    WorkLog("m-001", "2026-08-04", 3),
    WorkLog("m-002", "2026-08-04", 6),
    WorkLog("m-004", "2026-08-04", 8),
    WorkLog("m-001", "2026-08-05", 4),
    WorkLog("m-003", "2026-08-05", 5.5),
    WorkLog("m-004", "2026-08-05", 3),
    WorkLog("m-002", "2026-08-06", 2),
    WorkLog("m-004", "2026-08-07", 6),
)

mcp = MCPServer(name="team-dashboard-daily", version="0.1.0")


class ToolFailure(Exception):
    """業務ルール上ありえない入力を表す例外。

    SDK がこの例外を捕まえて isError: true のツール結果に変換します。
    TypeScript 版で `{ content: [...], isError: true }` を return していたのと同じ意味です。
    """


def find_member(member_id: str) -> Member | None:
    for member in MEMBERS:
        if member.id == member_id:
            return member
    return None


def days_between(date_from: str, date_to: str) -> int | None:
    """両端を含む日数。実在しない日付なら None（TypeScript 版の NaN に対応）"""
    try:
        start = datetime.date.fromisoformat(date_from)
        end = datetime.date.fromisoformat(date_to)
    except ValueError:
        return None
    return (end - start).days + 1


def format_hours(hours: float) -> str:
    """12 を "12"、18.5 を "18.5" と表示する（TypeScript の String(...) と揃える）"""
    return f"{round(hours, 1):g}"


def rows_of_day(date: str, team: str | None = None) -> list[tuple[Member, float]]:
    """指定日の稼働をメンバー別に集計する。team を渡すとそのチームだけに絞る"""
    buckets: dict[str, float] = {}
    for log in WORK_LOGS:
        if log.date != date:
            continue
        member = find_member(log.member_id)
        if member is None:
            continue
        if team is not None and member.team != team:
            continue
        buckets[log.member_id] = buckets.get(log.member_id, 0) + log.hours

    rows: list[tuple[Member, float]] = []
    for member_id in sorted(buckets):
        member = find_member(member_id)
        if member is not None:
            rows.append((member, buckets[member_id]))
    return rows


@mcp.tool(
    title="日次の稼働時間",
    # description を明示すると docstring より優先される。TypeScript 版と 1 文字も違わない文章にする
    description=(
        "指定した 1 日の稼働時間を、メンバー別の内訳付きで返します。"
        "team を指定するとそのチームだけに絞れます。"
        "複数日をまたぐ調査には busiest_day を使ってください。"
    ),
    structured_output=False,
)
def daily_hours(
    date: Annotated[
        str,
        Field(pattern=DATE_PATTERN, description="集計する日（YYYY-MM-DD）"),
    ],
    team: Annotated[
        TeamName | None,
        Field(description="特定のチームだけに絞る場合に指定します。省略すると全チームが対象です。"),
    ] = None,
) -> str:
    """指定日の稼働時間を集計する（AI 向けの説明文はデコレータの description= 側）。"""
    # 形式は Pydantic が保証済み。ここでは「形式は正しいが実在しない日付」を弾く
    if days_between(date, date) is None:
        raise ToolFailure("date には実在する日付を指定してください（例: 2026-08-04）。")

    rows = rows_of_day(date, team)
    total = sum(hours for _, hours in rows)
    scope = team if team is not None else "全チーム"
    header = (
        f"{date} の稼働時間（{scope}）: "
        f"合計 {format_hours(total)} 時間 / {len(rows)} 名"
    )
    if not rows:
        # 「0 件」は失敗ではない。正常な結果として返す
        return f"{header}\nこの日の稼働記録はありません。"

    lines = [
        f"- {member.name}（{member.id} / {member.team}）: {format_hours(hours)} 時間"
        for member, hours in rows
    ]
    return "\n".join([header, *lines])


@mcp.tool(
    title="最も忙しかった日",
    description=(
        "指定した期間のうち、チーム全体の稼働時間が最も多かった 1 日を返します。"
        "同じ時間の日が複数ある場合は最も早い日を返します。"
        f"1 回で調べられるのは最長 {MAX_RANGE_DAYS} 日です。"
    ),
    structured_output=False,
)
def busiest_day(
    date_from: Annotated[
        str,
        Field(
            alias="from",  # from は Python の予約語。電文上の名前だけを from にする
            pattern=DATE_PATTERN,
            description="調査期間の開始日（YYYY-MM-DD、この日を含む）",
        ),
    ],
    date_to: Annotated[
        str,
        Field(
            alias="to",
            pattern=DATE_PATTERN,
            description="調査期間の終了日（YYYY-MM-DD、この日を含む）",
        ),
    ],
) -> str:
    """期間内で最も稼働時間が多い日を返す（説明文はデコレータの description= 側）。"""
    span = days_between(date_from, date_to)
    if span is None:
        raise ToolFailure("from / to には実在する日付を指定してください（例: 2026-08-03）。")
    if span <= 0:
        raise ToolFailure(f"from（{date_from}）は to（{date_to}）以前の日付を指定してください。")
    if span > MAX_RANGE_DAYS:
        raise ToolFailure(
            f"調べられる期間は最長 {MAX_RANGE_DAYS} 日です（指定された期間は {span} 日）。"
            "期間を分けて複数回呼び出してください。"
        )

    totals: dict[str, float] = {}
    for log in WORK_LOGS:
        if log.date < date_from or log.date > date_to:
            continue
        totals[log.date] = totals.get(log.date, 0) + log.hours
    if not totals:
        # 「最も多い日」を返す契約なので、返す値が無い＝ツール実行の失敗
        raise ToolFailure(
            f"{date_from} 〜 {date_to} に稼働記録がありません。期間を広げて再試行してください。"
        )

    best_date = ""
    best_hours = -1.0
    for date in sorted(totals):  # 同点なら最も早い日を採る（安定した並びを先に作る）
        if totals[date] > best_hours:
            best_date = date
            best_hours = totals[date]

    count = len(rows_of_day(best_date))
    return (
        f"{date_from} 〜 {date_to} で最も稼働時間が多い日: "
        f"{best_date}（{format_hours(best_hours)} 時間 / {count} 名）"
    )
