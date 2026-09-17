"""社内申請ワークフロー MCP サーバー（Python 版・代表 2 ツール）

TypeScript 版のうち get_request / decide_request を移植します。
確認したいのは次の 3 点です。
  ① 例外を投げると isError: true になる（回復できる文面を例外に載せる）
  ② 辞書で返すと成功扱いになる（error フィールドは機械向け）
  ③ 返却量の上限はサーバーが持つ（本文の切り出し）

重要：stdout は JSON-RPC の通信路なので print() で書かない。ログは stderr へ。
このファイルは自己完結させています（データ層も同じファイルに小さく持ちます）。
"""

from __future__ import annotations

import sys
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from errors import ToolFailure, ToolFailureError

Decision = Literal["approve", "reject", "return_for_changes"]

#: 返す情報量の上限（サーバーが持つ）
BODY_CHARS = 400
SECTION_ITEMS = 5

#: ツールと必要スコープの対応（検証はセッション12）
TOOL_SCOPES = {"get_request": "requests:read", "decide_request": "requests:approve"}

#: この接続に与えられた権限。実運用では環境変数やトークンから決めます
GRANTED_SCOPES = ("requests:read", "requests:approve")

LONG_BODY = "提案力強化の外部研修（2 日間）への参加費です。" * 30


def create_store() -> dict[str, dict[str, Any]]:
    """呼ぶたびに同じ初期状態を返す（実行結果を再現できるようにするため）"""
    return {
        "req-1001": {
            "id": "req-1001",
            "title": "8月分の交通費精算",
            "status": "draft",
            "amountYen": 12_480,
            "body": "8月の顧客訪問 6 件分の交通費です。",
            "comments": [],
        },
        "req-1003": {
            "id": "req-1003",
            "title": "外部研修の参加費",
            "status": "in_review",
            "amountYen": 88_000,
            "body": LONG_BODY,
            "comments": [
                {"authorId": "u-900", "body": f"補足 {index}: 見積の内訳を確認しました。"}
                for index in range(1, 25)
            ],
        },
        "req-1004": {
            "id": "req-1004",
            "title": "夏季休暇（3日間）",
            "status": "approved",
            "amountYen": 0,
            "body": "8月26日から28日まで夏季休暇を取得します。",
            "comments": [],
        },
    }


store = create_store()
mcp = MCPServer(name="workflow-requests-py", version="1.1.0")


def next_action_for(status: str) -> str:
    return {
        "draft": "提出するには submit_request を使ってください。",
        "in_review": "決裁するには decide_request を使ってください。",
        "approved": "この申請は承認済みで、これ以上の変更はできません。",
        "rejected": "この申請は却下済みです。",
    }.get(status, "状態を確認してください。")


def classify(request_id: str, allowed: tuple[str, ...]) -> ToolFailure | None:
    """存在と状態を検査する（TypeScript 版の classify と同じ役目）"""
    row = store.get(request_id)
    if row is None:
        return ToolFailure(
            code="not_found",
            what=f"申請 {request_id} は見つかりません。",
            next="ID の形式は req-1001 です。search_requests で探して、返ってきた id を使ってください。",
            retryable=False,
        )
    if row["status"] not in allowed:
        return ToolFailure(
            code="invalid_state",
            what=f"申請 {request_id} は現在 {row['status']} です。",
            next=f"この操作ができるのは {' / '.join(allowed)} の申請だけです。{next_action_for(row['status'])}",
            retryable=False,
        )
    return None


def scope_guard(tool: str) -> ToolFailure | None:
    required = TOOL_SCOPES[tool]
    if required in GRANTED_SCOPES:
        return None
    return ToolFailure(
        code="forbidden",
        what=f"この操作には権限 {required} が必要ですが、現在の接続には付与されていません。",
        next="権限が必要な操作はユーザーに依頼してください。状況の確認だけなら get_request が使えます。",
        retryable=False,
    )


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
def get_request(
    request_id: Annotated[str, Field(pattern=r"^req-\d{4}$", description="申請 ID（req-1001 の形式）")],
    include: Annotated[
        list[Literal["comments"]] | None,
        Field(description="追加で含めるセクション。省略すると詳細だけを返します"),
    ] = None,
) -> str:
    """申請 1 件の詳細を返します。

    ID が分からないときは先に search_requests で探してください。
    本文が 400 文字を超える場合は先頭だけを返し、全文の在処を書き添えます。
    コメントは直近 5 件までです。
    """
    failure = scope_guard("get_request") or classify(request_id, ("draft", "in_review", "approved", "rejected"))
    if failure is not None:
        # 例外を投げると SDK が isError: true のツール結果に変換します
        raise ToolFailureError(failure)

    row = store[request_id]
    body = row["body"]
    if len(body) > BODY_CHARS:
        body = (
            f"{body[:BODY_CHARS]}…\n"
            f"（本文は {len(body)} 文字あるため先頭 {BODY_CHARS} 文字だけを返しました。"
            f"全文が必要なときはリソース request://{row['id']} を読んでください）"
        )

    comments = row["comments"]
    shown = comments[-SECTION_ITEMS:]
    suffix = f"のうち直近 {len(shown)} 件" if len(comments) > len(shown) else ""
    lines = [
        f"{row['id']} {row['title']}",
        f"金額: {row['amountYen']} 円 / 状態: {row['status']}",
        "本文:",
        body,
    ]
    if include and "comments" in include:
        lines.append(f"コメント（全 {len(comments)} 件{suffix}）:")
        lines += [f"- {comment['authorId']}: {comment['body']}" for comment in shown]
    return "\n".join(lines)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
def decide_request(
    request_id: Annotated[str, Field(pattern=r"^req-\d{4}$", description="決裁する申請の ID")],
    decision: Annotated[Decision, Field(description="approve / reject / return_for_changes")],
    comment: Annotated[
        str | None, Field(max_length=500, description="決裁理由。approve 以外では必須")
    ] = None,
    confirm: Annotated[bool, Field(description="False（既定）はドライラン")] = False,
) -> dict[str, Any]:
    """審査中の申請に決裁を下します。

    失敗の種類によって返し方が変わります。
      ・回復してほしい失敗（存在しない・状態が違う・理由がない）は例外を投げます
      ・処理はできたが結果として何もしなかった場合は辞書で返します（成功扱い）
    """
    failure = scope_guard("decide_request") or classify(request_id, ("in_review",))
    if failure is not None:
        raise ToolFailureError(failure)

    if decision != "approve" and not (comment or "").strip():
        raise ToolFailureError(
            ToolFailure(
                code="invalid_argument",
                what=f'decision="{decision}" では comment（理由）が必須です。',
                next="申請者に表示される理由を 1 文以上で comment に指定して呼び直してください。",
                retryable=False,
            )
        )

    row = store[request_id]
    if not confirm:
        return {
            "applied": False,
            "requestId": request_id,
            "decision": decision,
            "currentStatus": row["status"],
            "nextStatus": "approved" if decision == "approve" else "rejected",
            "hint": "確定するには confirm=True を付けて呼び直してください。",
        }

    row["status"] = "approved" if decision == "approve" else "rejected"
    return {
        "applied": True,
        "requestId": request_id,
        "decision": decision,
        "currentStatus": row["status"],
        "nextStatus": row["status"],
    }


if __name__ == "__main__":
    print(f"[workflow-requests-py] ツール {len(TOOL_SCOPES)} 本で待機しています", file=sys.stderr)
    mcp.run(transport="stdio")
