/**
 * 問題6 の解答：タイムアウトの二段構えを実験で確かめる
 *
 * 実行： docker compose exec node npx tsx src/session08/practice/q6-timeout.ts
 * （合計およそ 5 秒かかります）
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { McpError } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

const TOTAL_STEPS = 20;
const STEP_DELAY_MS = 120; // 1 ステップ 120ms × 20 = 約 2.4 秒
const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

function sleepOrAbort(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error("キャンセル済みです"));
      return;
    }
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(new Error("キャンセル通知を受け取ったため中断しました"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

const server = new McpServer({ name: "q6-timeout", version: "1.0.0" });

server.registerTool(
  "slow_aggregate",
  {
    title: "時間のかかる集計",
    description: "20 ステップの集計を行います。進捗通知とキャンセルに対応しています。",
    inputSchema: {},
    outputSchema: { steps: z.number().int(), total: z.number().int() },
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  },
  async (_args, extra) => {
    const progressToken = extra._meta?.progressToken;
    let executed = 0;
    try {
      for (let step = 0; step < TOTAL_STEPS; step++) {
        extra.signal.throwIfAborted();
        await sleepOrAbort(STEP_DELAY_MS, extra.signal);
        executed = step + 1;
        if (progressToken !== undefined) {
          await extra.sendNotification({
            method: "notifications/progress",
            params: { progressToken, progress: executed, total: TOTAL_STEPS },
          });
        }
      }
    } catch (error) {
      // タイムアウトしたクライアントはキャンセル通知を送る。
      // ここで止めないと、誰も待っていない処理が最後まで走り続ける
      console.error(`[slow_aggregate] 中断しました（cancelled=${extra.signal.aborted}）`);
      throw error;
    }
    return {
      content: [{ type: "text", text: `${executed}/${TOTAL_STEPS} ステップ完了` }],
      structuredContent: { steps: executed, total: TOTAL_STEPS },
    };
  },
);

// ---------------- 検証 ----------------
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "q6-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

const codeOf = (error: unknown): string =>
  error instanceof McpError ? String(error.code) : "不明";

// ケース1：進捗は届くが、タイムアウトは測り直されない
try {
  await client.callTool({ name: "slow_aggregate", arguments: {} }, undefined, {
    timeout: 500,
    onprogress: () => {},
  });
  console.log("[1/3] timeout=500ms: 完走（想定外）");
} catch (error) {
  console.log(`[1/3] timeout=500ms: タイムアウト（code=${codeOf(error)}）`);
}
await sleep(300); // サーバー側が中断処理を終えるのを待つ

// ケース2：進捗が届くたびにタイムアウトを測り直すので完走する
const result = await client.callTool({ name: "slow_aggregate", arguments: {} }, undefined, {
  timeout: 500,
  resetTimeoutOnProgress: true,
  onprogress: () => {},
});
const summary = result.structuredContent as { steps: number };
console.log(`[2/3] timeout=500ms + 進捗でリセット: 完走（steps=${summary.steps}）`);

// ケース3：進捗が届き続けても、絶対上限で打ち切られる
try {
  await client.callTool({ name: "slow_aggregate", arguments: {} }, undefined, {
    timeout: 500,
    resetTimeoutOnProgress: true,
    maxTotalTimeout: 1000,
    onprogress: () => {},
  });
  console.log("[3/3] maxTotalTimeout=1000ms: 完走（想定外）");
} catch (error) {
  console.log(
    `[3/3] timeout=500ms + 進捗でリセット + maxTotalTimeout=1000ms: 打ち切り（code=${codeOf(error)}）`,
  );
}
await sleep(300);

await client.close();
await server.close();
console.log("OK: 問題6 の条件を満たしています");
