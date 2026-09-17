"""セッション9 の検証用クライアント（Python 版）

    docker compose exec python python src/session09/verify.py

2 つのセッションを順に張ります。
  ① 3 機能に対応（コールバックを渡す）
  ② 何も渡さない（劣化経路）
クライアント側のスクリプトなので print() を使ってかまいません。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CreateMessageResult, ElicitResult, ListRootsResult, Root, TextContent

DOCS_ROOT = Path("src/mid01/docs").resolve()
PARAMS = StdioServerParameters(command="python", args=["src/session09/server.py"])

sampling_calls = 0
elicitation_calls = 0


async def sampling_callback(context: Any, params: Any) -> CreateMessageResult:
    """決まった文字列を返すダミー。実 LLM は使わない（出力を決定的にするため）"""
    global sampling_calls
    sampling_calls += 1
    text = "\n".join(
        message.content.text
        for message in params.messages
        if getattr(message.content, "type", "") == "text"
    )
    preferences = params.model_preferences
    return CreateMessageResult(
        model="stub-summarizer",
        role="assistant",
        content=TextContent(
            type="text",
            text=(
                f"【ダミー要約】{text.count('<document ')} 件の文書を要約しました"
                f"（cost={preferences.cost_priority} / speed={preferences.speed_priority}"
                f" / intelligence={preferences.intelligence_priority}）"
            ),
        ),
        stop_reason="endTurn",
    )


async def list_roots_callback(context: Any) -> ListRootsResult:
    return ListRootsResult(
        roots=[
            Root(uri=f"file://{DOCS_ROOT}/faq", name="FAQ"),
            Root(uri=f"file://{DOCS_ROOT}/guides", name="手順書"),
        ]
    )


async def elicitation_callback(context: Any, params: Any) -> ElicitResult:
    global elicitation_calls
    elicitation_calls += 1
    return ElicitResult(action="accept", content={"directory": "faq"})


def digest(structured: dict[str, Any]) -> str:
    return ", ".join(f"{hit['path']}({hit['score']})" for hit in structured.get("results", []))


async def main() -> None:
    async with stdio_client(PARAMS) as (read, write):
        async with ClientSession(
            read,
            write,
            sampling_callback=sampling_callback,
            list_roots_callback=list_roots_callback,
            elicitation_callback=elicitation_callback,
        ) as session:
            init = await session.initialize()
            print(f"[1/4] 接続: {init.server_info.name} v{init.server_info.version}")

            called = await session.call_tool("summarize_results", {"query": "連絡"})
            structured = called.structured_content or {}
            print(
                f"[2/4] 3 機能あり: scopeSource={structured.get('scopeSource')}"
                f" / scopeDirectories={structured.get('scopeDirectories')}"
                f" / narrowedBy={structured.get('narrowedBy')}"
                f" / totalMatched={structured.get('totalMatched')}"
                f" / 順序={digest(structured)}"
            )
            print(
                f"[3/4] 要約: source={structured.get('summarySource')}"
                f" / model={structured.get('model')}"
                f" / 1行目={structured.get('summary', '').splitlines()[0]}"
            )

    # 2 本目：コールバックを渡さない（3 機能を申告しないクライアント）
    async with stdio_client(PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            called = await session.call_tool("summarize_results", {"query": "連絡"})
            structured = called.structured_content or {}
            print(
                f"[4/4] 3 機能なし: scopeSource={structured.get('scopeSource')}"
                f" / narrowedBy={structured.get('narrowedBy')}"
                f" / totalMatched={structured.get('totalMatched')}"
                f" / source={structured.get('summarySource')}"
                f" / skipReason={structured.get('skipReason')}"
            )

    print("OK: Python 版でも同じ劣化経路が動いています")


if __name__ == "__main__":
    anyio.run(main)
