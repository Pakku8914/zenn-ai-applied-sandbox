"""セッション6 の確認用クライアント（Python 版）

実行： docker compose exec python python src/session06/verify.py

クライアント側のスクリプトなので print() を使ってかまいません。

mcp 2.0 ではモデルのフィールドが snake_case です（mime_type / list_changed）。
AttributeError が出たら SDK のバージョンと属性名を確認してください（15 節）。
"""

from __future__ import annotations

import json
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import PromptReference, ResourceTemplateReference

GLOSSARY_TEMPLATE = "glossary://{term}"
SUMMARY_URI = "dashboard://summary/current"

updated_uris: list[str] = []


async def handle_message(message: Any) -> None:
    """サーバーからの通知を数える（ServerNotification は root に本体が入る）"""
    notification = getattr(message, "root", None)
    if notification is not None and getattr(notification, "method", "") == (
        "notifications/resources/updated"
    ):
        updated_uris.append(str(notification.params.uri))


def line_count(text: str) -> int:
    return len(text.rstrip("\n").split("\n"))


async def main() -> None:
    params = StdioServerParameters(command="python", args=["src/session06/server.py"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, message_handler=handle_message) as session:
            init = await session.initialize()
            resources_capability = init.capabilities.resources
            print(
                f"[1/8] 接続: {init.server_info.name} v{init.server_info.version}"
                f" / resources.subscribe={getattr(resources_capability, 'subscribe', None)}"
                f" / resources.list_changed={getattr(resources_capability, 'list_changed', None)}"
                f" / completions={'あり' if init.capabilities.completions is not None else 'なし'}"
                f" / prompts={'あり' if init.capabilities.prompts is not None else 'なし'}"
            )

            listed = await session.list_resources()
            print(
                f"[2/8] resources/list: {len(listed.resources)} 件"
                f" → {', '.join(str(resource.uri) for resource in listed.resources)}"
            )

            templates = await session.list_resource_templates()
            names = sorted(template.uri_template for template in templates.resource_templates)
            print(f"[3/8] resources/templates/list: {len(names)} 件 → {', '.join(names)}")

            summary = (await session.read_resource(SUMMARY_URI)).contents[0]
            snapshot = json.loads(summary.text)
            print(
                f"[4/8] summary: mimeType={summary.mime_type}"
                f" / revision={snapshot['revision']} / totalHours={snapshot['totalHours']}"
            )

            term = (await session.read_resource("glossary://sprint")).contents[0]
            print(
                f"[5/8] glossary://sprint: mimeType={term.mime_type}"
                f" / 行数={line_count(term.text)} / 1行目={term.text.split(chr(10))[0]}"
            )

            ref = ResourceTemplateReference(type="ref/resource", uri=GLOSSARY_TEMPLATE)
            narrowed = await session.complete(ref, {"name": "term", "value": "c"})
            everything = await session.complete(ref, {"name": "term", "value": ""})
            print(
                f"[6/8] 補完（term=\"c\"）: {', '.join(narrowed.completion.values)}"
                f" / 補完（term=\"\"）: {len(everything.completion.values)} 件"
            )

            draft = await session.get_prompt(
                "weekly_report_draft",
                {"week_start": "2026-08-03", "week_end": "2026-08-07", "audience": "manager"},
            )
            second = draft.messages[1].content
            print(
                f"[7/8] prompts/get: messages={len(draft.messages)}"
                f" / 1件目={draft.messages[0].content.type}"
                f" / 2件目={second.type}（mimeType={second.resource.mime_type}）"
            )

            # 購読を試す（高水準 API がハンドラを持たない場合は -32601 が返る）
            try:
                await session.subscribe_resource(SUMMARY_URI)
                accepted = True
            except Exception:  # noqa: BLE001 ―― 受理されなかったことだけを見る
                accepted = False

            # Python 版の引数名は snake_case（TypeScript 版の memberId / projectId とは別物）
            added = await session.call_tool(
                "add_work_log",
                {
                    "member_id": "m-003",
                    "project_id": "p-report",
                    "date": "2026-08-07",
                    "hours": 3,
                },
            )
            # ツールの失敗は例外ではなく is_error=True の結果で返るので、必ず確認する
            if added.is_error:
                raise RuntimeError(getattr(added.content[0], "text", "add_work_log に失敗しました"))
            await anyio.sleep(0.2)
            revision = (added.structured_content or {}).get("revision")
            print(
                f"[8/8] 購読の受理={accepted} / add_work_log: revision={revision}"
                f" / updated 通知={len(updated_uris)} 件"
            )

            # 補完のプロンプト参照も同じ session.complete で呼べる
            prompt_ref = PromptReference(type="ref/prompt", name="weekly_report_draft")
            with_context = await session.complete(
                prompt_ref, {"name": "week_end", "value": ""}, {"week_start": "2026-08-03"}
            )
            print(f"[補足] week_end の候補（context あり）: {with_context.completion.values}")

    print("OK: Python 版でもリソース・テンプレート・補完・プロンプトが動作しています")


if __name__ == "__main__":
    anyio.run(main)
