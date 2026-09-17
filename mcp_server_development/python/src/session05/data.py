"""チーム稼働ダッシュボード ― データ層（Python / セッション5 版）

TypeScript 版（node/src/session05/data.ts）と同じデータ・同じ CSV になるように書いています。
プロトコルに出るキー名は TypeScript 版と揃えて camelCase にします
（Python の慣習は snake_case ですが、ここでは「クライアントから見た互換性」を優先します）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

MAX_RANGE_DAYS = 92
MAX_INLINE_BYTES = 2048


@dataclass(frozen=True, slots=True)
class Member:
    id: str
    name: str
    team: str
    weekly_capacity_hours: float


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class WorkLog:
    member_id: str
    project_id: str
    date: str
    hours: float


MEMBERS: list[Member] = [
    Member("m-001", "佐藤 花子", "platform", 40),
    Member("m-002", "鈴木 一郎", "platform", 40),
    Member("m-003", "田中 美咲", "data", 32),
    Member("m-004", "高橋 健", "data", 40),
]

PROJECTS: list[Project] = [
    Project("p-portal", "社内ポータル刷新"),
    Project("p-report", "稼働レポート整備"),
    Project("p-search", "全文検索基盤"),
]

WORK_LOGS: list[WorkLog] = [
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
]

#: アーカイブ済みプロジェクトの ID（プロセスが生きている間だけ保持）
_archived_project_ids: set[str] = set()


def find_member(member_id: str) -> Member | None:
    return next((member for member in MEMBERS if member.id == member_id), None)


def list_members(team: str | None = None) -> list[Member]:
    found = [member for member in MEMBERS if team is None or member.team == team]
    return sorted(found, key=lambda member: member.id)


def find_project(project_id: str) -> Project | None:
    return next((project for project in PROJECTS if project.id == project_id), None)


def list_active_projects() -> list[Project]:
    active = [project for project in PROJECTS if project.id not in _archived_project_ids]
    return sorted(active, key=lambda project: project.id)


def archive_project(project_id: str) -> dict[str, Any]:
    """プロジェクトをアーカイブする（冪等）。戻り値のキーは camelCase で返す"""
    project = find_project(project_id)
    if project is None:
        raise ValueError(f"unknown project: {project_id}")

    already_archived = project_id in _archived_project_ids
    _archived_project_ids.add(project_id)

    related = [log for log in WORK_LOGS if log.project_id == project_id]
    return {
        "projectId": project_id,
        "name": project.name,
        "alreadyArchived": already_archived,
        "archivedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "affectedWorkLogs": len(related),
        "affectedHours": round(sum(log.hours for log in related), 1),
        "remainingActiveProjects": [item.id for item in list_active_projects()],
    }


def build_report_rows(from_date: str, to_date: str) -> list[WorkLog]:
    """CSV に書き出す行。日付 → メンバー ID の昇順で固定する"""
    rows = [log for log in WORK_LOGS if from_date <= log.date <= to_date]
    return sorted(rows, key=lambda log: (log.date, log.member_id))


def format_hours(hours: float) -> str:
    """"6" / "7.5" のように TypeScript 版と同じ文字列にする"""
    return str(int(hours)) if float(hours).is_integer() else f"{hours:.1f}"


def to_csv(rows: list[WorkLog]) -> str:
    header = "date,memberId,projectId,hours"
    lines = [
        f"{log.date},{log.member_id},{log.project_id},{format_hours(log.hours)}" for log in rows
    ]
    return "\n".join([header, *lines]) + "\n"


def sum_hours(rows: list[WorkLog]) -> float:
    return round(sum(log.hours for log in rows), 1)


def byte_size_of(text: str) -> int:
    return len(text.encode("utf-8"))


def days_between(from_date: str, to_date: str) -> int:
    """両端を含む日数。日付として解釈できない場合は ValueError を投げる"""
    return (date.fromisoformat(to_date) - date.fromisoformat(from_date)).days + 1

def summarize_hours(
    from_date: str, to_date: str, member_id: str | None = None
) -> dict[str, Any]:
    """期間内の稼働時間をメンバー別に集計する（キーは camelCase で返す）"""
    targets = [
        log
        for log in WORK_LOGS
        if from_date <= log.date <= to_date and (member_id is None or log.member_id == member_id)
    ]

    buckets: dict[str, dict[str, Any]] = {}
    for log in targets:
        bucket = buckets.setdefault(log.member_id, {"hours": 0.0, "days": set()})
        bucket["hours"] += log.hours
        bucket["days"].add(log.date)

    rows: list[dict[str, Any]] = []
    for member_key in sorted(buckets):
        member = find_member(member_key)
        rows.append(
            {
                "memberId": member_key,
                "name": member.name if member else "(不明なメンバー)",
                "team": member.team if member else "(不明)",
                "totalHours": round(buckets[member_key]["hours"], 1),
                "workedDays": len(buckets[member_key]["days"]),
            }
        )

    return {
        # 出力のキーは Pydantic モデルのフィールド名になります。
        # from / to は Python の識別子にできないので startDate / endDate にします
        "startDate": from_date,
        "endDate": to_date,
        "totalHours": round(sum(row["totalHours"] for row in rows), 1),
        "memberCount": len(rows),
        "members": rows,
    }
