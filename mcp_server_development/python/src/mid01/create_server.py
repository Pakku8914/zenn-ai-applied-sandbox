"""社内ドキュメント検索 ― サーバー定義（Python / search_documents のみ）

要求仕様どおり、Python 版はツール 1 本だけを移植します。
リソース・プロンプト・補完は TypeScript 版だけの機能です（対応表を参照）。

この関数もトランスポートに接続しません（server.py の責務）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

import docs_domain as domain

#: 読み取り専用ツールの注釈。4 つすべてを明示する
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


class SearchHitOut(BaseModel):
    path: str = Field(description="公開ディレクトリからの相対パス")
    uri: str = Field(description="本文を読み取るための URI（docs://<path>）")
    title: str = Field(description="文書の見出し（1 行目の # 見出し）")
    score: int = Field(description="一致の強さ。見出しへの一致を高く重み付けしている")
    matchCount: int = Field(description="文書全体での一致回数（重み無し）")
    snippet: str = Field(description="一致した箇所の抜粋（60 文字まで）")


class SearchOut(BaseModel):
    query: str = Field(description="実際に検索に使った語")
    directory: str | None = Field(default=None, description="絞り込みに使ったディレクトリ")
    totalMatched: int = Field(description="一致した文書の総数（上限を適用する前）")
    returned: int = Field(description="このレスポンスに含めた件数")
    truncated: bool = Field(description="上限で打ち切ったか")
    results: list[SearchHitOut] = Field(description="スコア降順・パス昇順で並べた検索結果")


def create_docsearch_server(docs_root: Path) -> MCPServer:
    repository = domain.create_repository(docs_root)
    mcp = MCPServer(name="docsearch", version="0.1.0")

    @mcp.tool(
        name="search_documents",
        title="社内ドキュメントの全文検索",
        annotations=READ_ONLY,
    )
    def search_documents(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=domain.MAX_QUERY_LENGTH,
                description="検索語。空白区切りで複数指定すると AND 検索になります（最大 5 語）",
            ),
        ],
        limit: Annotated[
            int | None,
            Field(ge=1, le=domain.MAX_LIMIT, description="返す件数の上限（1〜20、既定 5）"),
        ] = None,
        directory: Annotated[
            str | None,
            Field(max_length=64, description="検索対象を絞るディレクトリ（例: guides）"),
        ] = None,
    ) -> SearchOut:
        """社内ドキュメント（Markdown）を全文検索し、一致した文書への参照を返します。

        本文はレスポンスに含めません。中身が必要な場合は、返された docs:// の URI を
        参照してください。読みたい文書の場所が分かっている場合は検索せずに直接読み取ってください。
        検索は部分一致です。
        """
        # ValueError は SDK が isError のツール結果に変換する
        return SearchOut(**domain.search_documents(repository, query, limit, directory))

    return mcp
