"""セッション5 の確認用クライアント（Python 版）

実行： docker compose exec python python src/session05/verify.py

クライアント側のスクリプトなので print() を使ってかまいません
（禁止されているのは「サーバープロセスの stdout」だけです）。

mcp 2.0 ではモデルのフィールドが snake_case です
（input_schema / output_schema / structured_content / is_error / mime_type）。
AttributeError が出る場合は SDK のバージョンを確認してください。
"""

from __future__ import annotations

from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def ensure_ok(result: Any, label: str) -> Any:
    """成功するはずの呼び出しを検査する。

    セッション経由の呼び出しでは、ツールの失敗は例外ではなく
    is_error=True のツール結果として返ってきます。確認しないと
    「壊れているのに動いているように見える」ので、明示的に落とします。
    """
    if result.is_error:
        raise RuntimeError(f"{label} が失敗しました: {getattr(result.content[0], 'text', '')}")
    return result


def describe(annotations: Any) -> str:
    """注釈を「ホストがどう解釈するか」に翻訳する（既定値の扱いが要点）"""
    if annotations is None:
        return "注釈なし"
    labels: list[str] = []
    read_only = annotations.read_only_hint is True
    if read_only:
        labels.append("読み取り専用")
    else:
        if annotations.destructive_hint is not False:  # 既定は True
            labels.append("破壊的")
        if annotations.idempotent_hint is True:
            labels.append("冪等")
    if annotations.open_world_hint is False:
        labels.append("閉じた世界")
    return "+".join(labels)


async def main() -> None:
    params = StdioServerParameters(command="python", args=["src/session05/server.py"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = sorted((await session.list_tools()).tools, key=lambda tool: tool.name)
            print(
                f"[1/7] 接続: {init.server_info.name} v{init.server_info.version} "
                f"/ tools={', '.join(tool.name for tool in tools)}"
            )

            by_name = {tool.name: tool for tool in tools}
            props = sorted((by_name["export_report"].input_schema.get("properties") or {}).keys())
            # 仮引数の名前がそのまま電文の引数名になっていることの確認
            print(f"[2/7] export_report の引数名: {', '.join(props)}")

            with_output = [tool.name for tool in tools if tool.output_schema is not None]
            without_output = [tool.name for tool in tools if tool.output_schema is None]
            print(
                f"[3/7] outputSchema あり: {', '.join(with_output)} "
                f"/ なし: {', '.join(without_output)}"
            )

            print(f"[4/7] 注釈: {' / '.join(f'{t.name}={describe(t.annotations)}' for t in tools)}")

            listed = ensure_ok(
                await session.call_tool("list_members", {"team": "platform"}), "list_members"
            )
            structured = listed.structured_content or {}
            print(
                f"[5/7] list_members: count={structured.get('count')} "
                f"/ members[0].memberId={structured['members'][0]['memberId']} "
                f"/ content 種別={listed.content[0].type}"
            )

            first = ensure_ok(
                await session.call_tool(
                    "archive_project",
                    {"project_id": "p-search", "reason": "検索基盤の刷新完了に伴う終了"},
                ),
                "archive_project（1回目）",
            )
            second = ensure_ok(
                await session.call_tool(
                    "archive_project",
                    {"project_id": "p-search", "reason": "重複呼び出しの確認"},
                ),
                "archive_project（2回目）",
            )
            # こちらは失敗するのが正しいので ensure_ok を通しません
            missing = await session.call_tool(
                "archive_project", {"project_id": "p-unknown", "reason": "存在しない ID の確認"}
            )
            payload = first.structured_content or {}
            print(
                f"[6/7] archive_project: 1回目 alreadyArchived={payload.get('alreadyArchived')} "
                f"/ 2回目={(second.structured_content or {}).get('alreadyArchived')} "
                f"/ affectedWorkLogs={payload.get('affectedWorkLogs')} "
                f"/ 未知の ID は isError={missing.is_error}"
            )

            exported = ensure_ok(
                await session.call_tool(
                    "export_report",
                    {"start_date": "2026-07-27", "end_date": "2026-08-07"},
                ),
                "export_report",
            )
            link = next(block for block in exported.content if block.type == "resource_link")
            print(
                f"[7/7] export_report: 種別={','.join(b.type for b in exported.content)} "
                f"/ uri={link.uri} / mimeType={link.mime_type}"
            )

    print("OK: Python 版でも outputSchema・注釈・resource_link が動作しています")


if __name__ == "__main__":
    anyio.run(main)
