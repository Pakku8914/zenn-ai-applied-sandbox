"""社内申請ワークフローのデータ層（Python 版）

MCP に依存しません。TypeScript 版（node/src/session10/data.ts）と同じ初期データを持ち、
同じ検索結果になるようにしています（カーソルは省略した縮小版です）。
"""

from __future__ import annotations

import base64
import json
from typing import Any, Literal

CATEGORIES = ("expense", "purchase", "leave", "travel")
STATUSES = ("draft", "in_review", "approved", "rejected")
DECISIONS = ("approve", "reject", "return_for_changes")

Category = Literal["expense", "purchase", "leave", "travel"]
Status = Literal["draft", "in_review", "approved", "rejected"]
Decision = Literal["approve", "reject", "return_for_changes"]

HIGH_AMOUNT_THRESHOLD = 50_000


def _route(amount_yen: int) -> list[dict[str, Any]]:
    """金額で承認段数が変わる（5 万円以上は課長 → 部長の 2 段階）"""
    route: list[dict[str, Any]] = [
        {"order": 1, "approverId": "u-900", "approverName": "山田 課長", "state": "pending"}
    ]
    if amount_yen >= HIGH_AMOUNT_THRESHOLD:
        route.append(
            {"order": 2, "approverId": "u-901", "approverName": "高橋 部長", "state": "pending"}
        )
    return route


def create_store() -> dict[str, Any]:
    """呼ぶたびに同じ初期状態を返す（実行結果を再現できるようにするため）"""
    tick = {"value": 0}

    def now() -> str:
        minutes = tick["value"]
        tick["value"] += 1
        return f"2026-08-20T09:{minutes:02d}:00.000Z"

    seed: list[dict[str, Any]] = [
        {
            "id": "req-1001",
            "title": "8月分の交通費精算",
            "category": "expense",
            "amountYen": 12_480,
            "applicantId": "u-001",
            "applicantName": "佐藤 花子",
            "department": "営業部",
            "status": "draft",
            "body": "8月の顧客訪問 6 件分の交通費です。",
            "updatedAt": "2026-08-18T09:10:00.000Z",
            "approvals": _route(12_480),
            "comments": [],
        },
        {
            "id": "req-1002",
            "title": "モニター 2 台の購入",
            "category": "purchase",
            "amountYen": 64_800,
            "applicantId": "u-002",
            "applicantName": "鈴木 一郎",
            "department": "開発部",
            "status": "in_review",
            "body": "開発用の 27 インチモニターを 2 台購入したいです。",
            "updatedAt": "2026-08-17T02:00:00.000Z",
            "approvals": _route(64_800),
            "comments": [],
        },
        {
            "id": "req-1003",
            "title": "外部研修の参加費",
            "category": "expense",
            "amountYen": 88_000,
            "applicantId": "u-001",
            "applicantName": "佐藤 花子",
            "department": "営業部",
            "status": "in_review",
            "body": "提案力強化の外部研修（2 日間）への参加費です。",
            "updatedAt": "2026-08-18T12:00:00.000Z",
            "approvals": _route(88_000),
            "comments": [
                {
                    "id": "c-01",
                    "authorId": "u-900",
                    "body": "見積書を添付してください。",
                    "postedAt": "2026-08-18T11:00:00.000Z",
                },
                {
                    "id": "c-02",
                    "authorId": "u-001",
                    "body": "添付しました。ご確認ください。",
                    "postedAt": "2026-08-18T12:00:00.000Z",
                },
            ],
        },
        {
            "id": "req-1004",
            "title": "夏季休暇（3日間）",
            "category": "leave",
            "amountYen": 0,
            "applicantId": "u-003",
            "applicantName": "田中 実",
            "department": "開発部",
            "status": "approved",
            "body": "8月26日から28日まで夏季休暇を取得します。",
            "updatedAt": "2026-08-11T00:00:00.000Z",
            "approvals": [
                {
                    "order": 1,
                    "approverId": "u-900",
                    "approverName": "山田 課長",
                    "state": "approved",
                }
            ],
            "comments": [],
        },
        {
            "id": "req-1005",
            "title": "大阪出張の旅費概算",
            "category": "travel",
            "amountYen": 43_200,
            "applicantId": "u-002",
            "applicantName": "鈴木 一郎",
            "department": "開発部",
            "status": "rejected",
            "body": "9月の展示会視察に伴う出張旅費の概算です。",
            "updatedAt": "2026-08-13T00:00:00.000Z",
            "approvals": [
                {
                    "order": 1,
                    "approverId": "u-900",
                    "approverName": "山田 課長",
                    "state": "rejected",
                }
            ],
            "comments": [],
        },
    ]
    return {"requests": {row["id"]: row for row in seed}, "next_number": 1006, "now": now}


def search_requests(
    store: dict[str, Any],
    query: str | None = None,
    status: list[str] | None = None,
    category: str | None = None,
    applicant_id: str | None = None,
    min_amount_yen: int | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """条件で絞り込み、要約（本文なし）の一覧を返す"""
    rows = sorted(store["requests"].values(), key=lambda row: row["id"])
    matched = []
    for row in rows:
        if query is not None and query.lower() not in f"{row['title']}\n{row['body']}".lower():
            continue
        if status and row["status"] not in status:
            continue
        if category is not None and row["category"] != category:
            continue
        if applicant_id is not None and row["applicantId"] != applicant_id:
            continue
        if min_amount_yen is not None and row["amountYen"] < min_amount_yen:
            continue
        matched.append(row)

    page = matched[:limit]
    return {
        "total": len(matched),
        "returned": len(page),
        "hasMore": len(matched) > len(page),
        "items": [
            {
                "id": row["id"],
                "title": row["title"],
                "category": row["category"],
                "status": row["status"],
                "amountYen": row["amountYen"],
                "applicantName": row["applicantName"],
                "updatedAt": row["updatedAt"],
            }
            for row in page
        ],
    }


def format_detail_text(store: dict[str, Any], request_id: str, include: list[str]) -> str | None:
    """詳細をテキストに整形する。include で追加セクションを選ぶ"""
    row = store["requests"].get(request_id)
    if row is None:
        return None
    lines = [
        f"{row['id']} {row['title']}",
        f"区分: {row['category']} / 金額: {row['amountYen']} 円 / 状態: {row['status']}",
        f"申請者: {row['applicantName']}（{row['applicantId']} / {row['department']}）",
        f"更新: {row['updatedAt']}",
        "本文:",
        row["body"],
        "承認ルート:",
        *[
            f"- {step['order']}. {step['approverName']}（{step['approverId']}）: {step['state']}"
            for step in row["approvals"]
        ],
    ]
    if "comments" in include:
        lines.append(f"コメント（{len(row['comments'])} 件）:")
        lines += [f"- {c['authorId']} {c['postedAt']}: {c['body']}" for c in row["comments"]]
    return "\n".join(lines)


def make_preview_token(request_id: str, updated_at: str, decision: str, comment: str | None) -> str:
    """ドライランと確定を結びつける識別子（認可の代わりではありません）"""
    payload = json.dumps(
        {
            "v": 1,
            "action": "decide",
            "requestId": request_id,
            "updatedAt": updated_at,
            "decision": decision,
            "comment": comment,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def preview_decision(
    store: dict[str, Any], request_id: str, decision: str, comment: str | None
) -> dict[str, Any]:
    """決裁の予告。ok が False のときは message に理由が入る"""
    row = store["requests"].get(request_id)
    if row is None:
        return {"ok": False, "message": f"申請 {request_id} は見つかりません。"}
    if row["status"] != "in_review":
        return {
            "ok": False,
            "message": (
                f"申請 {request_id} は {row['status']} のため決裁できません。"
                "決裁できるのは in_review の申請だけです。"
            ),
        }
    if decision != "approve" and not (comment or "").strip():
        return {
            "ok": False,
            "message": f'decision="{decision}" では comment（理由）が必須です。',
        }

    pending = [step for step in row["approvals"] if step["state"] == "pending"]
    if not pending:
        return {"ok": False, "message": f"申請 {request_id} に未処理の承認ステップがありません。"}
    is_last = len(pending) == 1
    next_status = (
        "rejected"
        if decision == "reject"
        else "draft"
        if decision == "return_for_changes"
        else "approved"
        if is_last
        else "in_review"
    )
    notify_to = (
        [pending[1]["approverName"]]
        if decision == "approve" and not is_last
        else [row["applicantName"]]
    )
    return {
        "ok": True,
        "requestId": request_id,
        "decision": decision,
        "currentStatus": row["status"],
        "nextStatus": next_status,
        "stepLabel": f"{pending[0]['order']}/{len(row['approvals'])} 段目",
        "finalizes": next_status != "in_review",
        "notifyTo": notify_to,
        "previewToken": make_preview_token(request_id, row["updatedAt"], decision, comment),
    }


def apply_decision(
    store: dict[str, Any], request_id: str, decision: str, comment: str | None
) -> dict[str, Any]:
    """決裁を確定する"""
    preview = preview_decision(store, request_id, decision, comment)
    if not preview["ok"]:
        return preview
    row = store["requests"][request_id]
    at = store["now"]()
    current = next(step for step in row["approvals"] if step["state"] == "pending")
    if decision == "approve":
        current["state"] = "approved"
    elif decision == "reject":
        current["state"] = "rejected"
    else:
        row["approvals"] = _route(row["amountYen"])
    row["status"] = preview["nextStatus"]
    row["updatedAt"] = at
    if comment:
        row["comments"].append(
            {
                "id": f"c-{len(row['comments']) + 1:02d}",
                "authorId": current["approverId"],
                "body": comment,
                "postedAt": at,
            }
        )
    return {
        "ok": True,
        "status": row["status"],
        "stepLabel": preview["stepLabel"],
        "finalizes": preview["finalizes"],
    }
