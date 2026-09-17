"""問題7 の解答：Python 側に report://excel/{period}.csv を追加する

本文の create_dashboard_server() が返す MCPServer にデコレータで追記します。
戻り値の型を bytes にするだけで、SDK が base64 に変換して blob として送ります。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src/session06")  # 本文のモジュールを import できるようにする

import data  # noqa: E402
from create_server import create_dashboard_server  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402


def create_dashboard_server_q7() -> MCPServer:
    mcp = create_dashboard_server()

    @mcp.resource(
        "report://excel/{period}.csv",
        name="weekly_report_excel_csv",
        description=(
            "指定期間の稼働記録を BOM 付き UTF-16LE の CSV として返します（Excel 向け）。"
            "プログラムから処理する場合は report://weekly/ を読んでください。"
        ),
        mime_type="text/csv; charset=utf-16le",
    )
    def read_weekly_report_excel(period: str) -> bytes:
        parsed = data.parse_period(period)
        if parsed is None:
            raise ValueError("period は 2026-08-03_2026-08-07 の形式で指定してください。")
        from_date, to_date = parsed
        csv = data.to_excel_csv(data.build_report_rows(from_date, to_date))
        # "utf-16" は BOM 付きリトルエンディアン。"utf-16-le" だと BOM が付かない
        return csv.encode("utf-16")

    return mcp
