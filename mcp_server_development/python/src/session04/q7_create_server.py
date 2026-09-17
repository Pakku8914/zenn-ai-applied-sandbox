"""問題7: 1.x 向けコードを 2.0 に移行したサーバー定義

修正前のコードは「動かない」だけでなく、
仮に動いても本文の Python 版とは別のツールになっていました。
電文を本文と一致させることを目標に直しています。
"""

from typing import Annotated

from mcp.server.mcpserver import MCPServer  # ① クラス名と import パス
from pydantic import Field

import data
from create_server import DATE_PATTERN, MemberIdStr, ToolFailure, format_summary

# ② コンストラクタはキーワード引数。version も明示する
mcp = MCPServer(name="team-dashboard", version="0.1.0")


# ③ 関数名がツール名になる。camelCase をやめて TypeScript 版と同じ名前にする
@mcp.tool(
    title="稼働時間の集計",
    # ⑤ 引数の説明を docstring から追い出し、ツール全体の説明だけを description に置く
    description=(
        "指定した期間の稼働時間をメンバー別に集計し、合計と内訳を返します。"
        "期間は開始日・終了日の両方を含みます。"
        f"1 回で集計できるのは最長 {data.MAX_RANGE_DAYS} 日です。"
    ),
    # ⑧ 戻り値の型から構造化出力が自動生成されるのを抑止する
    structured_output=False,
)
def summarize_hours(
    # ④ 電文上の名前は仮引数の名前そのもの。from_ も memberId も捨て、
    #    予約語でない snake_case に統一する（alias では解決できません）
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
    # ⑥ 「指定なし」は空文字ではなく None
    member_id: Annotated[
        MemberIdStr | None,
        Field(
            description="特定のメンバーだけを集計する場合に指定します。省略すると全員が対象です。",
        ),
    ] = None,
) -> str:  # ⑦ 戻り値はテキスト 1 つ
    """（AI 向けの説明文はデコレータの description= 側に書いています）"""
    # ⑨ 業務ルールの検証を追加する
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

    return format_summary(data.summarize_hours(start_date, end_date, member_id))
