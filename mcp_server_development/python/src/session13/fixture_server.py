"""テスト専用のサーバー（fixture / Python 版）

TypeScript 版（node/src/session13/fixture-server.ts）の echo_text と
同じ契約（同じツール名・同じ引数名・同じ注釈・同じ出力テキスト）になるように書いています。
「同じ契約なのに tools/list の中身は違う」ことを確かめるための土台です。
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

FIXTURE_NAME = "session13-fixture"
FIXTURE_VERSION = "1.0.0"

#: 読み取り専用ツールの注釈。TypeScript 版と同じ 4 つを明示する
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def create_fixture_server() -> MCPServer:
    mcp = MCPServer(name=FIXTURE_NAME, version=FIXTURE_VERSION)

    @mcp.tool(name="echo_text", title="テキストのエコー", annotations=READ_ONLY)
    def echo_text(
        text: Annotated[
            str,
            Field(min_length=1, max_length=100, description="繰り返す対象のテキスト（1〜100 文字）"),
        ],
        count: Annotated[int | None, Field(ge=1, le=5, description="繰り返す回数（1〜5、既定 1）")] = None,
    ) -> str:
        """受け取ったテキストを指定回数だけ繰り返して返します。テストの土台を確かめるためのツールです。"""
        return "\n".join([text] * (count or 1))

    return mcp
