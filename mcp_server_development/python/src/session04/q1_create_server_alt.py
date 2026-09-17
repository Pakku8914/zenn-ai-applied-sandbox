"""別解: 独立した MCPServer インスタンスを作る（TypeScript 版の構成に近い）"""

from mcp.server.mcpserver import MCPServer

import create_server
import data

mcp = MCPServer(name="team-dashboard", version="0.1.0")

# 本文の関数をそのまま登録する。@mcp.tool() は関数を書き換えないので再利用できます
mcp.tool(title="メンバー一覧", structured_output=False)(create_server.list_members)
mcp.tool(
    title="稼働時間の集計",
    description=(
        "指定した期間の稼働時間をメンバー別に集計し、合計と内訳を返します。"
        "期間は開始日・終了日の両方を含みます。"
        f"1 回で集計できるのは最長 {data.MAX_RANGE_DAYS} 日です。"
    ),
    structured_output=False,
)(create_server.summarize_hours)

# ここに list_projects を @mcp.tool() で追加する（省略）
