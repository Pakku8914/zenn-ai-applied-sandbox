"""中間プロジェクト1 の検証用クライアント（Python 版）

実行： docker compose exec python python src/mid01/verify.py

クライアント側のスクリプトなので print() を使ってかまいません。

mcp 2.0 ではモデルのフィールドが snake_case です（output_schema / read_only_hint）。
版によって名前が変わりうる箇所は getattr で受けています。AttributeError が出たら
`python -c "import mcp.types as t; print([n for n in dir(t.Tool)])"` で確認してください。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import docs_domain as domain

DOCS_ROOT = Path("src/mid01/docs")

#: ドメイン層で確認する危険な入力（Python 版はリソースを公開しないため直接呼ぶ）
DANGEROUS_PATHS: list[tuple[str, str]] = [
    ("../../etc/passwd", "parent_traversal"),
    ("/etc/passwd", "absolute_path"),
    ("..%2f..%2fetc%2fpasswd", "parent_traversal"),
    ("C:\\windows\\win.ini", "drive_letter"),
    ("onboarding.txt", "not_markdown"),
    ("a/b/c/d/e.md", "too_deep"),
]


def digest(result: dict[str, Any]) -> str:
    return ", ".join(f"{hit['path']}({hit['score']})" for hit in result.get("results", []))


async def main() -> None:
    params = StdioServerParameters(command="python", args=["src/mid01/server.py"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"[1/6] 接続: {init.server_info.name} v{init.server_info.version}")

            tools = (await session.list_tools()).tools
            tool = tools[0]
            annotations = tool.annotations
            has_output_schema = getattr(tool, "output_schema", None) is not None
            print(
                f"[2/6] tools/list: {len(tools)} 本 → {tool.name}"
                f" / read_only_hint={getattr(annotations, 'read_only_hint', None)}"
                f" / outputSchema={'あり' if has_output_schema else 'なし'}"
            )

            vpn = await session.call_tool("search_documents", {"query": "VPN"})
            vpn_result = vpn.structured_content or {}
            print(
                f'[3/6] query="VPN": totalMatched={vpn_result.get("totalMatched")}'
                f" / 順序={digest(vpn_result)}"
            )

            faq = await session.call_tool(
                "search_documents", {"query": "ロック", "directory": "faq"}
            )
            print(f'[4/6] directory="faq": 順序={digest(faq.structured_content or {})}')

            conjunction = await session.call_tool("search_documents", {"query": "障害 連絡"})
            print(f"[5/6] AND 検索: 順序={digest(conjunction.structured_content or {})}")

            invalid = await session.call_tool("search_documents", {"query": "   "})
            is_error = getattr(invalid, "is_error", getattr(invalid, "isError", None))
            message = invalid.content[0].text if invalid.content else ""
            print(f"[6/6] 不正な検索語: isError={is_error} / message={message}")

    # ドメイン層のパス検証（MCP を通さないので判定理由まで確認できる）
    repository = domain.create_repository(DOCS_ROOT.resolve())
    verdicts: list[str] = []
    for raw, expected in DANGEROUS_PATHS:
        try:
            repository.read_document(raw)
            verdicts.append(f"{raw}=許可されてしまった")
        except domain.DocAccessError as error:
            mark = "OK" if error.reason == expected else "NG"
            verdicts.append(f"{raw}={error.reason}[{mark}]")
    print("[パス検証] " + " / ".join(verdicts))
    print("OK: Python 版でも search_documents が同じ結果を返しています")


if __name__ == "__main__":
    anyio.run(main)
