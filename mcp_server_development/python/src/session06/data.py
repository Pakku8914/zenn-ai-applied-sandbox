"""チーム稼働ダッシュボード ― データ層（Python / セッション6 版）

TypeScript 版（node/src/session06/data.ts）と同じデータ・同じ CSV になるように書いています。
プロトコルに出るキー名は TypeScript 版と揃えて camelCase にします
（Python の慣習は snake_case ですが、クライアントから見た互換性を優先します）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

MAX_RANGE_DAYS = 92
MAX_INLINE_BYTES = 2048
DASHBOARD_FROM = "2026-07-27"
DASHBOARD_TO = "2026-08-07"

#: URI に載る用語スラッグの許可リスト
TERM_SLUG_PATTERN = re.compile(r"^[a-z0-9-]{1,32}$")
#: report://weekly/{period}.csv の period
PERIOD_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$")


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


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    slug: str
    term: str
    category: str
    definition: str
    related: tuple[str, ...]


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

#: 稼働記録。追加できるように可変リストで持つ
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

#: 集計結果の改訂番号（時刻ではなく連番にして出力を再現可能にする）
_revision = 1

#: スラッグ昇順で持つ（補完の候補順が安定する）
GLOSSARY: list[GlossaryEntry] = [
    GlossaryEntry("capacity", "キャパシティ", "稼働管理",
                  "1 週間に投入できる稼働時間の上限。メンバーごとに設定します。",
                  ("utilization", "wip")),
    GlossaryEntry("cycle-time", "サイクルタイム", "指標",
                  "作業に着手してから完了するまでの経過時間。", ("lead-time", "wip")),
    GlossaryEntry("lead-time", "リードタイム", "指標",
                  "依頼を受けてから完了するまでの経過時間。待ち時間を含みます。", ("cycle-time",)),
    GlossaryEntry("okr", "OKR", "目標管理",
                  "目標（Objective）と主要な成果（Key Results）で四半期の目標を管理する手法。",
                  ("velocity",)),
    GlossaryEntry("oncall", "オンコール", "運用",
                  "障害対応の当番。稼働時間とは別枠で記録します。", ("toil", "postmortem")),
    GlossaryEntry("postmortem", "ポストモーテム", "運用",
                  "障害の後に原因と再発防止策をまとめる文書。個人の責任を問わないのが原則です。",
                  ("oncall",)),
    GlossaryEntry("sprint", "スプリント", "開発プロセス",
                  "1〜2 週間の固定期間。この区切りで計画と振り返りを行います。",
                  ("velocity", "story-point")),
    GlossaryEntry("story-point", "ストーリーポイント", "指標",
                  "作業量の相対見積もり単位。時間ではなく難しさの比で表します。",
                  ("velocity", "sprint")),
    GlossaryEntry("toil", "トイル", "運用",
                  "手作業で繰り返し発生し、価値を生まない運用作業。自動化の候補になります。",
                  ("oncall",)),
    GlossaryEntry("utilization", "稼働率", "稼働管理",
                  "実績の稼働時間をキャパシティで割った値。100% を目標にしない指標です。",
                  ("capacity",)),
    GlossaryEntry("velocity", "ベロシティ", "指標",
                  "1 スプリントで完了したストーリーポイントの合計。", ("sprint", "story-point")),
    GlossaryEntry("wip", "WIP（Work In Progress）", "開発プロセス",
                  "着手済みで完了していない作業。同時に持てる上限を決めて運用します。",
                  ("cycle-time", "capacity")),
]


def find_member(member_id: str) -> Member | None:
    return next((member for member in MEMBERS if member.id == member_id), None)


def find_project(project_id: str) -> Project | None:
    return next((project for project in PROJECTS if project.id == project_id), None)


def find_term(slug: str) -> GlossaryEntry | None:
    return next((entry for entry in GLOSSARY if entry.slug == slug), None)


def complete_term_slugs(prefix: str) -> list[str]:
    """補完の候補。入力値による絞り込みはサーバー側の責務"""
    needle = prefix.strip().lower()
    return sorted(entry.slug for entry in GLOSSARY if entry.slug.startswith(needle))


def render_term_markdown(entry: GlossaryEntry) -> str:
    """用語 1 件を Markdown にする（常に 5 行）"""
    return "\n".join(
        [
            f"# {entry.term}（{entry.slug}）",
            "",
            f"- 分類: {entry.category}",
            f"- 定義: {entry.definition}",
            f"- 関連: {', '.join(entry.related)}",
        ]
    )


def normalize_slug(raw: str) -> str | None:
    """パーセントデコードを 1 回だけ行い、許可リストに照合する"""
    from urllib.parse import unquote

    decoded = unquote(raw)
    return decoded if TERM_SLUG_PATTERN.match(decoded) else None


def summarize_hours(from_date: str, to_date: str) -> dict:
    targets = [log for log in WORK_LOGS if from_date <= log.date <= to_date]
    buckets: dict[str, dict] = {}
    for log in targets:
        bucket = buckets.setdefault(log.member_id, {"hours": 0.0, "days": set()})
        bucket["hours"] += log.hours
        bucket["days"].add(log.date)

    rows = []
    for member_id in sorted(buckets):
        member = find_member(member_id)
        rows.append(
            {
                "memberId": member_id,
                "name": member.name if member else "(不明なメンバー)",
                "team": member.team if member else "(不明)",
                "totalHours": round(buckets[member_id]["hours"], 1),
                "workedDays": len(buckets[member_id]["days"]),
            }
        )
    return {
        "from": from_date,
        "to": to_date,
        "totalHours": round(sum(row["totalHours"] for row in rows), 1),
        "members": rows,
    }


def get_dashboard_snapshot() -> dict:
    summary = summarize_hours(DASHBOARD_FROM, DASHBOARD_TO)
    return {
        "revision": _revision,
        "from": summary["from"],
        "to": summary["to"],
        "totalHours": summary["totalHours"],
        "memberCount": len(summary["members"]),
        "members": summary["members"],
    }


def add_work_log(member_id: str, project_id: str, day: str, hours: float) -> dict:
    """稼働記録を 1 件追加する（冪等ではない）。改訂番号を 1 進める"""
    global _revision
    WORK_LOGS.append(WorkLog(member_id, project_id, day, hours))
    _revision += 1
    return {
        "revision": _revision,
        "entries": len(WORK_LOGS),
        "totalHours": get_dashboard_snapshot()["totalHours"],
    }


def build_report_rows(from_date: str, to_date: str) -> list[WorkLog]:
    rows = [log for log in WORK_LOGS if from_date <= log.date <= to_date]
    return sorted(rows, key=lambda log: (log.date, log.member_id))


def format_hours(hours: float) -> str:
    return str(int(hours)) if float(hours).is_integer() else f"{hours:.1f}"


def to_csv(rows: list[WorkLog]) -> str:
    header = "date,memberId,projectId,hours"
    lines = [
        f"{log.date},{log.member_id},{log.project_id},{format_hours(log.hours)}" for log in rows
    ]
    return "\n".join([header, *lines]) + "\n"


def to_excel_csv(rows: list[WorkLog]) -> str:
    """人が Excel で開く用。列名と値を日本語にする"""
    header = "日付,メンバー,プロジェクト,時間"
    lines = []
    for log in rows:
        member = find_member(log.member_id)
        project = find_project(log.project_id)
        lines.append(
            f"{log.date},{member.name if member else log.member_id},"
            f"{project.name if project else log.project_id},{format_hours(log.hours)}"
        )
    return "\n".join([header, *lines]) + "\n"


def sum_hours(rows: list[WorkLog]) -> float:
    return round(sum(log.hours for log in rows), 1)


def byte_size_of(text: str) -> int:
    return len(text.encode("utf-8"))


def days_between(from_date: str, to_date: str) -> int:
    """両端を含む日数。日付として解釈できない場合は ValueError"""
    return (date.fromisoformat(to_date) - date.fromisoformat(from_date)).days + 1


def parse_period(period: str) -> tuple[str, str] | None:
    matched = PERIOD_PATTERN.match(period)
    return (matched.group(1), matched.group(2)) if matched else None


def list_week_starts() -> list[str]:
    """補完候補にする直近 4 週の月曜日（固定値：実行日に依存させない）"""
    return ["2026-07-13", "2026-07-20", "2026-07-27", "2026-08-03"]


def week_end_of(week_start: str) -> str:
    try:
        return (date.fromisoformat(week_start) + timedelta(days=4)).isoformat()
    except ValueError:
        return week_start
