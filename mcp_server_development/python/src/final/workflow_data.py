"""社内申請ワークフローのドメイン層（Python 版・検索と詳細に必要な範囲だけ）

TypeScript 版（node/src/final/domain/workflow.ts）と同じ 24 件を持ちます。
検索の期待値が一致することが、この移植のゴールです。
MCP には依存しません（mcp を import しません）。
"""

from dataclasses import dataclass, field
from typing import Literal

Category = Literal["expense", "purchase", "leave", "travel"]
Status = Literal["draft", "in_review", "approved", "rejected"]

CATEGORIES: tuple[Category, ...] = ("expense", "purchase", "leave", "travel")
STATUSES: tuple[Status, ...] = ("draft", "in_review", "approved", "rejected")

CATEGORY_LABEL: dict[str, str] = {
    "expense": "経費精算",
    "purchase": "物品購入",
    "leave": "休暇",
    "travel": "出張",
}

# 本文をそのまま返す上限（TypeScript 版の BUDGET.bodyChars と同じ）
BODY_CHARS = 400

APPLICANTS = (
    ("u-001", "佐藤 花子", "営業部"),
    ("u-002", "鈴木 一郎", "開発部"),
    ("u-003", "田中 実", "開発部"),
)


@dataclass
class WorkflowRequest:
    id: str
    title: str
    category: str
    amount_yen: int
    applicant_id: str
    applicant_name: str
    department: str
    status: str
    body: str
    updated_at: str
    comments: list[tuple[str, str]] = field(default_factory=list)


_BASE: list[WorkflowRequest] = [
    WorkflowRequest(
        "req-1001", "8月分の交通費精算", "expense", 12480, "u-001", "佐藤 花子", "営業部",
        "draft", "8月の顧客訪問 6 件分の交通費です。内訳は経路ごとに記載しました。",
        "2026-08-18T09:10:00.000Z",
    ),
    WorkflowRequest(
        "req-1002", "モニター 2 台の購入", "purchase", 64800, "u-002", "鈴木 一郎", "開発部",
        "in_review",
        "開発用の 27 インチモニターを 2 台購入したいです。既存機は 5 年以上経過しています。",
        "2026-08-17T02:00:00.000Z",
    ),
    WorkflowRequest(
        "req-1003", "外部研修の参加費", "expense", 88000, "u-001", "佐藤 花子", "営業部",
        "in_review",
        "提案力強化の外部研修（2 日間）への参加費です。受講後に社内へ共有会を実施します。",
        "2026-08-18T12:00:00.000Z",
        [("u-900", "見積書を添付してください。"), ("u-001", "添付しました。ご確認ください。")],
    ),
    WorkflowRequest(
        "req-1004", "夏季休暇（3日間）", "leave", 0, "u-003", "田中 実", "開発部",
        "approved", "8月26日から28日まで夏季休暇を取得します。", "2026-08-11T00:00:00.000Z",
    ),
    WorkflowRequest(
        "req-1005", "大阪出張の旅費概算", "travel", 43200, "u-002", "鈴木 一郎", "開発部",
        "rejected", "9月の展示会視察に伴う出張旅費の概算です。", "2026-08-13T00:00:00.000Z",
    ),
]

# (category, status, applicant_index, amount_yen) ―― TypeScript 版の GENERATED と同じ順序
_GENERATED: tuple[tuple[str, str, int, int], ...] = (
    ("expense", "approved", 0, 15000),
    ("purchase", "in_review", 1, 31000),
    ("leave", "approved", 2, 0),
    ("travel", "draft", 0, 52000),
    ("expense", "rejected", 1, 8000),
    ("purchase", "approved", 2, 120000),
    ("leave", "in_review", 0, 0),
    ("travel", "approved", 1, 76000),
    ("expense", "draft", 2, 4300),
    ("purchase", "in_review", 0, 28000),
    ("leave", "approved", 1, 0),
    ("travel", "rejected", 2, 91000),
    ("expense", "approved", 0, 6700),
    ("purchase", "draft", 1, 45000),
    ("leave", "approved", 2, 0),
    ("travel", "in_review", 0, 33000),
    ("expense", "approved", 1, 9800),
    ("purchase", "rejected", 2, 150000),
    ("travel", "draft", 0, 64000),
)


def create_store() -> dict[str, WorkflowRequest]:
    """呼ぶたびに同じ 24 件から始まるストアを返す。"""
    store: dict[str, WorkflowRequest] = {request.id: request for request in _BASE}
    for index, (category, status, applicant, amount) in enumerate(_GENERATED):
        request_id = f"req-{1006 + index}"
        label = CATEGORY_LABEL[category]
        user_id, name, department = APPLICANTS[applicant]
        day = f"{10 + index:02d}"
        store[request_id] = WorkflowRequest(
            request_id,
            f"{label}の申請（{request_id}）",
            category,
            amount,
            user_id,
            name,
            department,
            status,
            f"{label}に関する申請です。金額は {amount} 円で、部門長の確認を受けています。",
            f"2026-07-{day}T06:00:00.000Z",
        )
    return store


def search(
    store: dict[str, WorkflowRequest],
    query: str | None = None,
    status: list[str] | None = None,
    category: str | None = None,
    applicant_id: str | None = None,
    min_amount_yen: int | None = None,
    limit: int = 10,
) -> tuple[int, list[WorkflowRequest]]:
    """TypeScript 版の searchRequests と同じ絞り込み・同じ並び順（ID 昇順）。"""
    matched: list[WorkflowRequest] = []
    for request in sorted(store.values(), key=lambda item: item.id):
        if query is not None and query.lower() not in f"{request.title}\n{request.body}".lower():
            continue
        if status and request.status not in status:
            continue
        if category is not None and request.category != category:
            continue
        if applicant_id is not None and request.applicant_id != applicant_id:
            continue
        if min_amount_yen is not None and request.amount_yen < min_amount_yen:
            continue
        matched.append(request)
    return len(matched), matched[:limit]


def summary_line(request: WorkflowRequest) -> str:
    return (
        f"- {request.id} {request.title}"
        f"（{request.category} / {request.amount_yen} 円 / {request.status}"
        f" / 申請者 {request.applicant_name}）"
    )


def detail_text(request: WorkflowRequest, include: list[str] | None = None) -> str:
    body = request.body
    if len(body) > BODY_CHARS:
        body = (
            f"{body[:BODY_CHARS]}…\n"
            f"（本文は {len(body)} 文字あるため先頭 {BODY_CHARS} 文字だけを返しました。"
            f"全文はリソース request://{request.id} を読んでください）"
        )
    lines = [
        f"{request.id} {request.title}",
        f"区分: {request.category} / 金額: {request.amount_yen} 円 / 状態: {request.status}",
        f"申請者: {request.applicant_name}（{request.applicant_id} / {request.department}）",
        f"更新: {request.updated_at}",
        "本文:",
        body,
    ]
    if include and "comments" in include:
        lines.append(f"コメント（全 {len(request.comments)} 件）:")
        lines.extend(f"- {author}: {text}" for author, text in request.comments)
    return "\n".join(lines)
