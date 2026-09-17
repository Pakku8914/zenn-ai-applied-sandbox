"""社内申請ワークフロー MCP サーバー（Python 版・2 ツールの移植）

TypeScript 版と「電文の引数名」を一致させることを最優先しています。
そのため仮引数を camelCase で書いています（PEP 8 には反しますが、
Python SDK は Field(alias=...) を付けても仮引数名で関数を呼ぶため、
電文の名前を合わせる方法がこれしかありません）。

サーバープロセスの標準出力には書きません（ログは logging = stderr）。
"""

import logging
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

import workflow_data as data

logger = logging.getLogger(__name__)

mcp = MCPServer(name="workflow-requests", version="1.0.0")
store = data.create_store()

REQUEST_ID_PATTERN = r"^req-\d{4}$"
USER_ID_PATTERN = r"^u-\d{3}$"


class ToolFailure(Exception):
    """SDK が捕まえて isError: true のツール結果に変換する例外。"""


@mcp.tool(
    title="申請を探す",
    description=(
        "申請を条件で絞り込み、要約の一覧を返します（本文は返しません）。"
        "ID が既に分かっているときは get_request を使ってください。"
    ),
    structured_output=False,
)
def search_requests(
    query: Annotated[
        str | None, Field(description="題名と本文に対する部分一致の検索語", max_length=100)
    ] = None,
    status: Annotated[
        list[str] | None, Field(description="状態で絞り込む（draft / in_review / approved / rejected）")
    ] = None,
    category: Annotated[
        str | None, Field(description="申請区分（expense / purchase / leave / travel）")
    ] = None,
    applicantId: Annotated[  # noqa: N803 電文の引数名を TypeScript 版に合わせる
        str | None, Field(description="申請者のユーザー ID（u-001 の形式）", pattern=USER_ID_PATTERN)
    ] = None,
    minAmountYen: Annotated[  # noqa: N803
        int | None, Field(description="金額の下限（円）", ge=0)
    ] = None,
    limit: Annotated[int, Field(description="返す件数（1〜50、既定は 10）", ge=1, le=50)] = 10,
) -> str:
    """申請を条件で絞り込む。"""
    if status is not None and any(value not in data.STATUSES for value in status):
        raise ToolFailure(
            f"status に指定できるのは {', '.join(data.STATUSES)} だけです。"
        )
    if category is not None and category not in data.CATEGORIES:
        raise ToolFailure(
            f"category に指定できるのは {', '.join(data.CATEGORIES)} だけです。"
        )
    total, page = data.search(
        store,
        query=query,
        status=status,
        category=category,
        applicant_id=applicantId,
        min_amount_yen=minAmountYen,
        limit=limit,
    )
    header = f"{total} 件中 {len(page)} 件"
    return "\n".join([header, *(data.summary_line(request) for request in page)])


@mcp.tool(
    title="申請の詳細を見る",
    description=(
        "申請 1 件の詳細を返します。ID が分からないときは先に search_requests で探してください。"
        f"本文は {data.BODY_CHARS} 文字で切ります。"
    ),
    structured_output=False,
)
def get_request(
    requestId: Annotated[  # noqa: N803
        str, Field(description="申請 ID（req-1001 の形式）", pattern=REQUEST_ID_PATTERN)
    ],
    include: Annotated[
        list[str] | None, Field(description="追加で含めるセクション（comments）")
    ] = None,
) -> str:
    """申請 1 件の詳細を返す。"""
    request = store.get(requestId)
    if request is None:
        # 内部の詳細を渡さず、次の一手だけを書く
        raise ToolFailure(
            f"申請 {requestId} は見つかりません。search_requests で ID を確認してください。"
        )
    return data.detail_text(request, include)
