"""横断復習2 問題7 ― 社内お知らせ掲示板（Python 版サーバー定義）

TypeScript 版（q4-create-server.ts）との違いが集中するので、コメントを多めにしています。
  ① ツール名は関数名になるので name= で明示する（契約だから）
  ② 注釈は ToolAnnotations（snake_case）で書く。電文上は camelCase になる
  ③ コンテンツブロックの列を返すツールは構造化出力を持てない
  ④ テンプレート変数名と関数の引数名を一致させる
  ⑤ 補完は @mcp.completion() の 1 ハンドラに集約する
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import Completion, ContentBlock, ResourceLink, TextContent, ToolAnnotations
from pydantic import Field

import q7_board as board

NOTICE_TEMPLATE = "notice://{slug}"

#: 読み取り専用ツールに付ける注釈（destructive / idempotent は意味を持たないので書かない）
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def create_notice_server() -> MCPServer:
    mcp = MCPServer(name="notice-board", version="0.1.0")

    @mcp.tool(name="search_notices", title="社内お知らせの検索", annotations=READ_ONLY)
    def search_notices(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=100,
                description="検索語。お知らせのタイトルと本文を対象に部分一致で探します",
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=board.MAX_LIMIT,
                description=(
                    f"返す最大件数（1〜{board.MAX_LIMIT}、既定 {board.DEFAULT_LIMIT}）。"
                    "ヒット総数は本文の要約を見てください"
                ),
            ),
        ] = board.DEFAULT_LIMIT,
        category: Annotated[
            Literal["all", "facility", "general", "hr", "it"],
            Field(
                description=(
                    "分類で絞り込みます"
                    "（facility: 設備 / general: 総務 / hr: 人事 / it: 情報システム / all: 絞り込みなし）"
                )
            ),
        ] = "all",
    ) -> list[ContentBlock]:
        """社内お知らせ掲示板をタイトルと本文の部分一致で検索し、参照（resource_link）を返します。

        本文はレスポンスに含めません。必要なお知らせだけ notice://{slug} を
        resources/read で読み取ってください。読みたいお知らせのスラッグが
        既に分かっている場合は、検索せず notice://{slug} を直接読んでください。
        """
        hits = board.match_notices(query, category)
        returned = hits[:limit]
        scope = (
            "すべての分類" if category == "all" else f"{board.label_of(category)}（{category}）"
        )

        if not returned:
            # 「0 件」は失敗ではない。例外を投げず、次の行動を促すテキストを返す
            return [
                TextContent(
                    type="text",
                    text=(
                        f"「{query}」に一致するお知らせは {scope} にありません。"
                        "別の語で検索するか、category を all にして絞り込みを外してください。"
                    ),
                )
            ]

        summary = (
            f"「{query}」に {len(hits)} 件ヒットしました"
            f"（{scope} / 上位 {len(returned)} 件を返しています）。"
            "本文はレスポンスに含めていません。必要なお知らせの uri を resources/read で読み取ってください。"
        )
        blocks: list[ContentBlock] = [TextContent(type="text", text=summary)]
        for hit in returned:
            matched = "タイトル一致" if hit["matchedIn"] == "title" else "本文一致"
            blocks.append(
                ResourceLink(
                    type="resource_link",
                    uri=f"notice://{hit['slug']}",
                    name=hit["slug"],
                    title=hit["title"],
                    mime_type="text/markdown",
                    description=f"{board.label_of(hit['category'])} / {hit['publishedOn']} / {matched}",
                )
            )
        return blocks

    @mcp.resource(
        NOTICE_TEMPLATE,
        name="notice_detail",
        description=(
            "社内お知らせ 1 件の本文を Markdown で返します。"
            "slug は英小文字・数字・ハイフンからなるスラッグです（例: summer-holiday）。"
            "指定できる値は completion/complete で取得できます。"
        ),
        mime_type="text/markdown",
    )
    def read_notice(slug: str) -> str:
        normalized = board.normalize_slug(slug)
        notice = board.find_notice(normalized) if normalized else None
        if notice is None:
            # リソースの失敗は例外で表す（isError はツールだけの仕組み）。
            # 受け取った値はメッセージに含めない
            raise ValueError(
                "指定されたお知らせは存在しません。"
                f"有効なスラッグの例: {', '.join(board.list_slugs()[:3])}"
                f"（全 {len(board.list_slugs())} 件）。"
                "候補は completion/complete で取得できます。"
            )
        return board.render_notice_markdown(notice)

    @mcp.completion()
    async def complete_argument(ref: Any, argument: Any, context: Any) -> Completion | None:
        """ref.type の文字列で判定する（参照クラスの名前は改訂で変わった経緯があるため）"""
        value: str = argument.value or ""
        if ref.type == "ref/resource" and str(ref.uri) == NOTICE_TEMPLATE:
            if argument.name == "slug":
                return Completion(values=board.complete_slugs(value))
        return None

    return mcp
