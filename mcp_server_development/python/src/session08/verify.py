"""動作確認用クライアント（Python 版）

実行： docker compose exec python python src/session08/verify.py

クライアント側のスクリプトなので print() を使ってかまいません
（禁止されているのは「サーバープロセスの stdout」だけです）。
"""

from __future__ import annotations

import json
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import LoggingMessageNotificationParams

TOTAL_STEPS = 20
log_counts: dict[str, int] = {}


async def on_log(params: LoggingMessageNotificationParams) -> None:
    """notifications/message を数える。通知は応答を返せないので受信側で数える"""
    log_counts[params.level] = log_counts.get(params.level, 0) + 1


def payload(result: Any) -> dict[str, Any]:
    """ツール結果の 1 つめのテキストを JSON として読む"""
    return json.loads(result.content[0].text)


async def main() -> None:
    params = StdioServerParameters(command="python", args=["src/session08/server.py"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, logging_callback=on_log) as session:
            init = await session.initialize()
            names = sorted(tool.name for tool in (await session.list_tools()).tools)
            print(
                f"[1/5] 接続: {init.server_info.name} v{init.server_info.version} "
                f"/ tools={', '.join(names)}"
            )

            # ---- ページネーション ----
            page1 = payload(await session.call_tool("list_observations", {"limit": 3}))
            page2 = payload(
                await session.call_tool(
                    "list_observations", {"limit": 3, "cursor": page1["nextCursor"]}
                )
            )
            ids1 = ", ".join(row["id"] for row in page1["observations"])
            print(
                f"[2/5] ページネーション: 1ページ目={ids1} "
                f"/ nextCursor={'あり' if page1.get('nextCursor') else 'なし'} "
                f"/ 2ページ目先頭={page2['observations'][0]['id']}"
            )

            # ---- 進捗通知 ----
            received = {"count": 0, "progress": 0, "total": 0}

            async def on_progress(
                progress: float, total: float | None, message: str | None
            ) -> None:
                received["count"] += 1
                received["progress"] = int(progress)
                received["total"] = int(total or 0)

            aggregated = payload(
                await session.call_tool(
                    "aggregate_observations",
                    {"chunk_delay_ms": 20},
                    progress_callback=on_progress,
                )
            )
            print(
                f"[3/5] 進捗通知: 受信={received['count']}回 "
                f"/ 最後={received['progress']}/{received['total']} "
                f"/ 集計件数={aggregated['totalObservations']}"
            )

            # ---- キャンセル ----
            with anyio.CancelScope() as scope:

                async def cancel_at_third(
                    progress: float, total: float | None, message: str | None
                ) -> None:
                    # 時間ではなくステップで判定するので結果が安定します
                    if progress >= 3:
                        scope.cancel()

                await session.call_tool(
                    "aggregate_observations",
                    {"chunk_delay_ms": 120},
                    progress_callback=cancel_at_third,
                )

            await anyio.sleep(0.5)  # キャンセル通知がサーバーに届くのを待つ
            report = payload(await session.call_tool("get_last_run_report", {}))
            print(
                f"[4/5] キャンセル: サーバー側 cancelled={report['cancelled']} "
                f"/ executedSteps<{TOTAL_STEPS}={report['executedSteps'] < TOTAL_STEPS}"
            )

            # ---- ロギング ----
            log_counts.clear()
            await session.call_tool("aggregate_observations", {"chunk_delay_ms": 0})
            print(
                f"[5/5] ログ通知: info={log_counts.get('info', 0)} "
                f"debug={log_counts.get('debug', 0)}"
            )

    print("OK: Python 版でもページネーション・進捗・キャンセル・ロギングが動作しています")


if __name__ == "__main__":
    anyio.run(main)
