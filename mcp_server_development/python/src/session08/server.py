"""気象観測データ MCP サーバー（Python / stdio）

TypeScript 版と同じ 4 つの機構を実装します。
  - ページネーション : list_observations
  - 進捗通知         : aggregate_observations（ctx.report_progress）
  - キャンセル       : aggregate_observations（await 地点でキャンセルが届く）
  - ロギング         : ctx.info / ctx.debug（notifications/message）

重要：stdout は JSON-RPC の通信路なので print() で書かない。ログは stderr へ。
"""

from __future__ import annotations

import math
import sys
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from observations import (
    TOTAL_STEPS,
    accumulate,
    decode_cursor,
    encode_cursor,
    find_start_index,
    get_observations,
    summarize,
    to_public,
)

mcp = MCPServer(name="weather-observations", version="1.0.0")

#: キャンセルが本当に効いたかを外から確認するための実行記録
_last_run: dict[str, Any] = {
    "tool": "aggregate_observations",
    "totalSteps": TOTAL_STEPS,
    "executedSteps": 0,
    "finished": False,
    "cancelled": False,
}


@mcp.tool()
def list_observations(
    cursor: str | None = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    station_id: str | None = None,
) -> dict[str, Any]:
    """気象観測レコードを観測時刻の昇順で返します。

    1 回の呼び出しで返す件数には上限があるため、続きを取得するにはレスポンスの
    nextCursor をそのまま cursor に渡してください。cursor の中身は解釈しないでください。

    Args:
        cursor: 前回のレスポンスの nextCursor。省略すると先頭から返します
        limit: 1 回で返す最大件数（1〜200、既定 50）
        station_id: 観測所 ID で絞り込みます（例: st-01）
    """
    rows = get_observations()
    if station_id is not None:
        rows = [row for row in rows if row.station_id == station_id]

    # decode_cursor が投げる ValueError は SDK が isError のツール結果に変換してくれます
    start = 0 if cursor is None else find_start_index(rows, decode_cursor(cursor))
    page = rows[start : start + limit]
    has_more = start + len(page) < len(rows)

    result: dict[str, Any] = {
        "observations": [to_public(row) for row in page],
        "returned": len(page),
        "hasMore": has_more,
    }
    if has_more and page:
        # 最後のページでは nextCursor を付けない。これが「終わり」の合図になる
        result["nextCursor"] = encode_cursor(page[-1].id)
    return result


@mcp.tool()
async def aggregate_observations(
    ctx: Context,
    station_id: str | None = None,
    chunk_delay_ms: Annotated[int, Field(ge=0, le=1000)] = 120,
) -> dict[str, Any]:
    """全観測レコードを観測所ごとに集計します。

    処理に数秒かかるため、進捗通知を送り、キャンセルにも対応します。

    Args:
        station_id: 観測所 ID で絞り込みます（例: st-01）
        chunk_delay_ms: 1 チャンクあたりの疑似待ち時間（ミリ秒）。学習用の擬似負荷です
    """
    rows = get_observations()
    if station_id is not None:
        rows = [row for row in rows if row.station_id == station_id]
    chunk_size = math.ceil(len(rows) / TOTAL_STEPS)
    acc: dict[str, dict[str, int]] = {}
    executed = 0

    _last_run.update(executedSteps=0, finished=False, cancelled=False)
    await ctx.info("集計を開始しました")

    try:
        for step in range(TOTAL_STEPS):
            # await する地点があることがキャンセルの前提です。
            # ここを同期の time.sleep にすると、キャンセル通知を読む隙がなくなります
            await anyio.sleep(chunk_delay_ms / 1000)

            accumulate(acc, rows[step * chunk_size : (step + 1) * chunk_size])
            executed = step + 1

            await ctx.debug(f"チャンク {executed}/{TOTAL_STEPS} を集計しました")
            # 進捗トークンが無ければ SDK 側で何もしない（送りっぱなしの通知）
            await ctx.report_progress(
                progress=executed,
                total=TOTAL_STEPS,
                message=f"{executed}/{TOTAL_STEPS} チャンク完了",
            )
    except anyio.get_cancelled_exc_class():
        _last_run.update(executedSteps=executed, finished=False, cancelled=True)
        print("[aggregate] 集計を中断しました（cancelled=True）", file=sys.stderr)
        # キャンセル例外は必ず再送出する。握りつぶすと anyio の構造化並行性が壊れます
        raise

    _last_run.update(executedSteps=executed, finished=True, cancelled=False)
    await ctx.info("集計が完了しました")
    return {"totalObservations": len(rows), "steps": executed, "stations": summarize(acc)}


@mcp.tool()
def get_last_run_report() -> dict[str, Any]:
    """直前に実行した aggregate_observations の実行記録を返します。

    何ステップ処理し、キャンセルされたかが分かります（キャンセル実装の検証用）。
    """
    return dict(_last_run)


if __name__ == "__main__":
    # ログは stderr へ。stdout は JSON-RPC 専用なので絶対に汚さない
    print("[weather-observations] stdio で待機しています", file=sys.stderr)
    mcp.run(transport="stdio")
