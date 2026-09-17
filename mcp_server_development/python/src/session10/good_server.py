"""社内申請ワークフロー MCP サーバー（Python 版・代表 3 ツール）

TypeScript 版の 6 ツールのうち、search_requests / get_request / decide_request を移植します。
粒度・命名・列挙型・既定値・二段階の論点はこの 3 本で確認できます。

重要：stdout は JSON-RPC の通信路なので print() で書かない。ログは stderr へ。
"""

from __future__ import annotations

import sys
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from workflow_data import (
    Category,
    Decision,
    Status,
    apply_decision,
    create_store,
    format_detail_text,
    preview_decision,
    search_requests as search_in_store,
)

#: ツールと必要スコープの対応（検証はセッション12）
TOOL_SCOPES = {
    "search_requests": "requests:read",
    "get_request": "requests:read",
    "decide_request": "requests:approve",
}

mcp = MCPServer(name="workflow-requests", version="1.0.0")
store = create_store()


@mcp.tool(
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def search_requests(
    query: Annotated[str | None, Field(description="題名と本文に対するキーワード検索（部分一致）")] = None,
    status: Annotated[
        list[Status] | None,
        Field(description="状態で絞り込む（複数指定可）。省略するとすべての状態を対象にします"),
    ] = None,
    category: Annotated[
        Category | None, Field(description="申請区分。この 4 種類以外は存在しません")
    ] = None,
    applicant_id: Annotated[
        str | None, Field(pattern=r"^u-\d{3}$", description="申請者のユーザー ID（u-001 の形式）")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="返す件数（1〜50、既定は 10）")] = 10,
) -> dict[str, Any]:
    """申請を条件で絞り込み、要約の一覧を返します（本文は返しません）。

    ID が既に分かっているときは get_request を使ってください。
    """
    return search_in_store(
        store,
        query=query,
        status=list(status) if status else None,
        category=category,
        applicant_id=applicant_id,
        limit=limit,
    )


@mcp.tool(
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def get_request(
    request_id: Annotated[str, Field(pattern=r"^req-\d{4}$", description="申請 ID（req-1001 の形式）")],
    include: Annotated[
        list[str] | None,
        Field(description="追加で含めるセクション（comments）。省略すると詳細と承認ルートだけを返します"),
    ] = None,
) -> str:
    """申請 1 件の詳細（題名・本文・金額・状態・承認ルートの進行状況）を返します。

    ID が分からないときは先に search_requests で探してください。
    コメントは既定では返しません。判断に必要なときだけ include に指定してください。
    """
    text = format_detail_text(store, request_id, include or [])
    if text is None:
        return f"申請 {request_id} は見つかりません。search_requests で ID を確認してください。"
    return text


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def decide_request(
    request_id: Annotated[str, Field(pattern=r"^req-\d{4}$", description="決裁する申請の ID")],
    decision: Annotated[
        Decision,
        Field(
            description=(
                "approve=承認（最終段なら承認確定）/ reject=却下（終了）/ "
                "return_for_changes=申請者へ差し戻して下書きに戻す"
            )
        ),
    ],
    comment: Annotated[
        str | None,
        Field(max_length=500, description="決裁理由。reject と return_for_changes では必須"),
    ] = None,
    confirm: Annotated[
        bool, Field(description="False（既定）はドライラン。True で実際に決裁します")
    ] = False,
    preview_token: Annotated[
        str | None, Field(description="ドライランの結果に含まれる値をそのまま渡します")
    ] = None,
) -> dict[str, Any]:
    """審査中の申請に決裁を下します。決裁は取り消せないため二段階です。

    まず confirm を付けずに呼んで、何段目の決裁か・確定後の状態・通知先・previewToken を
    受け取り、ユーザーの承諾を得てから confirm=True と preview_token を付けて呼び直してください。
    """
    preview = preview_decision(store, request_id, decision, comment)
    if not preview["ok"]:
        return {"applied": False, "error": preview["message"]}

    if not confirm:
        return {
            "applied": False,
            "stepLabel": preview["stepLabel"],
            "currentStatus": preview["currentStatus"],
            "nextStatus": preview["nextStatus"],
            "finalizes": preview["finalizes"],
            "notifyTo": preview["notifyTo"],
            "previewToken": preview["previewToken"],
            "hint": "確定するには confirm=True と preview_token を付けて再度呼び出してください。",
        }
    if preview_token != preview["previewToken"]:
        return {
            "applied": False,
            "error": (
                "preview_token が一致しません（未指定または申請の内容が変わっています）。"
                "confirm を省略して呼び出し、内容を確認してから確定してください。"
            ),
        }

    applied = apply_decision(store, request_id, decision, comment)
    return {
        "applied": True,
        "status": applied["status"],
        "stepLabel": applied["stepLabel"],
        "finalizes": applied["finalizes"],
    }


if __name__ == "__main__":
    print(f"[workflow-requests] ツール {len(TOOL_SCOPES)} 本で待機しています", file=sys.stderr)
    mcp.run(transport="stdio")
