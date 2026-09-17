/**
 * 気象観測データ MCP サーバー（Bad 実装）
 *
 * わざと 2 つの手抜きをしています。
 *   - 進捗通知を送らない（progressToken を無視する）
 *   - キャンセルを無視する（extra.signal を見ない）
 *
 * このファイルは verify-bad.ts から子プロセスとして起動されます。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import {
  accumulate,
  getObservations,
  summarize,
  TOTAL_STEPS,
  type StationAccumulator,
} from "./observations.js";

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

let executedSteps = 0;

const server = new McpServer({ name: "weather-observations-bad", version: "1.0.0" });

server.registerTool(
  "aggregate_observations",
  {
    title: "観測データの集計（Bad 実装）",
    description: "全観測レコードを観測所ごとに集計します。",
    inputSchema: {
      chunkDelayMs: z.number().int().min(0).max(1000).default(120),
    },
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  },
  // ❌ 第 2 引数 extra を受け取っていない = キャンセルにも進捗にも対応できない
  async ({ chunkDelayMs }) => {
    const rows = getObservations();
    const chunkSize = Math.ceil(rows.length / TOTAL_STEPS);
    const acc = new Map<string, StationAccumulator>();
    executedSteps = 0;
    for (let step = 0; step < TOTAL_STEPS; step++) {
      await sleep(chunkDelayMs);
      accumulate(acc, rows.slice(step * chunkSize, (step + 1) * chunkSize));
      executedSteps = step + 1;
    }
    return {
      content: [
        { type: "text", text: `${rows.length} 件を ${summarize(acc).length} 観測所に集計しました` },
      ],
    };
  },
);

server.registerTool(
  "get_last_run_report",
  {
    title: "直前の集計の実行記録",
    description: "直前の集計が何ステップ処理したかを JSON 文字列で返します。",
    inputSchema: {},
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  },
  async () => ({
    // Bad 実装はキャンセルを検知できないので、cancelled は常に false になる
    content: [{ type: "text", text: JSON.stringify({ executedSteps, cancelled: false }) }],
  }),
);

await server.connect(new StdioServerTransport());
console.error("[weather-observations-bad] stdio で待機しています");
