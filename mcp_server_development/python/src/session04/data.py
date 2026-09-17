"""チーム稼働ダッシュボード ― データ層

このファイルには MCP の要素が 1 つも出てきません。それが狙いです。
「サーバーの中身」＝ドメインロジックを MCP から独立させておくと、
テスト・移植・機能追加のたびにプロトコル層を触らずに済みます。

セッション3 の node/src/session03/data.ts を Python に移植したものです。
関数名・フィールド名は PEP 8 に合わせて snake_case にしていますが、
集計結果はどちらの言語でも完全に同じになります。

実務では、ここが DB アクセスや社内 API 呼び出しに置き換わります。
本章では学習のためインメモリの固定データを使います。
"""

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    team: str
    weekly_capacity_hours: int


@dataclass(frozen=True)
class Project:
    id: str
    name: str


@dataclass(frozen=True)
class WorkLog:
    member_id: str
    project_id: str
    # YYYY-MM-DD 形式。この形式は文字列のまま辞書順で比較できるので日付ライブラリが不要です
    date: str
    hours: float


# 集計できる期間の上限（日数）。
# 上限を設けるのは「巨大な期間を指定されて処理が終わらない」事故を防ぐためです。
# リソース枯渇対策の詳細はセッション15 で扱います。
MAX_RANGE_DAYS = 92

MEMBERS: tuple[Member, ...] = (
    Member("m-001", "佐藤 花子", "platform", 40),
    Member("m-002", "鈴木 一郎", "platform", 40),
    Member("m-003", "田中 美咲", "data", 32),
    Member("m-004", "高橋 健", "data", 40),
)

PROJECTS: tuple[Project, ...] = (
    Project("p-portal", "社内ポータル刷新"),
    Project("p-report", "稼働レポート整備"),
    Project("p-search", "全文検索基盤"),
)

WORK_LOGS: tuple[WorkLog, ...] = (
    WorkLog("m-001", "p-portal", "2026-07-27", 6),
    WorkLog("m-002", "p-search", "2026-07-27", 8),
    WorkLog("m-001", "p-portal", "2026-07-28", 7),
    WorkLog("m-003", "p-report", "2026-07-29", 5),
    WorkLog("m-004", "p-search", "2026-07-30", 4),
    WorkLog("m-001", "p-portal", "2026-08-03", 5),
    WorkLog("m-002", "p-search", "2026-08-03", 7.5),
    WorkLog("m-003", "p-report", "2026-08-03", 6),
    WorkLog("m-001", "p-search", "2026-08-04", 3),
    WorkLog("m-002", "p-search", "2026-08-04", 6),
    WorkLog("m-004", "p-portal", "2026-08-04", 8),
    WorkLog("m-001", "p-portal", "2026-08-05", 4),
    WorkLog("m-003", "p-report", "2026-08-05", 5.5),
    WorkLog("m-004", "p-search", "2026-08-05", 3),
    WorkLog("m-002", "p-report", "2026-08-06", 2),
    WorkLog("m-004", "p-search", "2026-08-07", 6),
)


@dataclass(frozen=True)
class MemberHours:
    member_id: str
    name: str
    team: str
    total_hours: float
    worked_days: int


@dataclass(frozen=True)
class HoursSummary:
    date_from: str
    date_to: str
    total_hours: float
    members: list[MemberHours]


def find_member(member_id: str) -> Member | None:
    """メンバー ID からメンバーを引く。見つからなければ None"""
    for member in MEMBERS:
        if member.id == member_id:
            return member
    return None


def list_members(team: str | None = None) -> list[Member]:
    """メンバー一覧を返す。team を指定するとそのチームだけに絞る。

    並び順を ID の昇順で固定しているのは、呼び出すたびに順番が変わらないようにするためです
    （順番が安定していないと、後のセッションで書くスナップショットテストが壊れます）。
    """
    found = [member for member in MEMBERS if team is None or member.team == team]
    return sorted(found, key=lambda member: member.id)


def summarize_hours(
    date_from: str, date_to: str, member_id: str | None = None
) -> HoursSummary:
    """期間内の稼働時間をメンバー別に集計する。

    date_from / date_to はどちらも「その日を含む」。
    稼働記録が 1 件もないメンバーは結果に含めない。
    """
    targets = [
        log
        for log in WORK_LOGS
        if date_from <= log.date <= date_to
        and (member_id is None or log.member_id == member_id)
    ]

    hours_by_member: dict[str, float] = {}
    days_by_member: dict[str, set[str]] = {}
    for log in targets:
        hours_by_member[log.member_id] = hours_by_member.get(log.member_id, 0) + log.hours
        days_by_member.setdefault(log.member_id, set()).add(log.date)

    rows: list[MemberHours] = []
    for target_id in sorted(hours_by_member):
        member = find_member(target_id)
        rows.append(
            MemberHours(
                member_id=target_id,
                name=member.name if member is not None else "(不明なメンバー)",
                team=member.team if member is not None else "(不明)",
                total_hours=round_hours(hours_by_member[target_id]),
                worked_days=len(days_by_member[target_id]),
            )
        )

    return HoursSummary(
        date_from=date_from,
        date_to=date_to,
        total_hours=round_hours(sum(row.total_hours for row in rows)),
        members=rows,
    )


def days_between(date_from: str, date_to: str) -> int | None:
    """date_from から date_to までの日数（両端を含む）。

    実在しない日付（2026-02-31 など）が渡された場合は None を返す。
    TypeScript 版では UTC 固定の工夫が必要でしたが、Python の date 型は
    タイムゾーンを持たないので、その心配がありません。
    """
    try:
        start = datetime.date.fromisoformat(date_from)
        end = datetime.date.fromisoformat(date_to)
    except ValueError:
        return None
    return (end - start).days + 1


def round_hours(hours: float) -> float:
    """小数第 1 位に丸める。浮動小数点の誤差が表示に出るのを防ぐため"""
    return round(hours, 1)


def format_hours(hours: float) -> str:
    """12.0 を "12"、15.5 を "15.5" と表示する。

    Python の float はそのまま f-string に入れると 12.0 と出ます。
    TypeScript 版の表示（12）と一致させるために書式を指定しています。
    """
    return f"{hours:g}"
