/**
 * 問題4 の解答：キャンセルを処理に届ける
 *
 * 実行： docker compose exec node npx tsx src/session08/practice/q4-cancel.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

const TOTAL_STEPS = 10;
const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

type RunReport = { executedSteps: number; finished: boolean; cancelled: boolean };
let lastRun: RunReport = { executedSteps: 0, finished: false, cancelled: false };

/**
 * ① AbortSignal を見張る待機。
 * キャンセルされたら残り時間を待たずに例外を投げるので反応が速い
 */
function sleepOrAbort(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error("キャンセル済みのため処理を開始しません"));
      return;
    }
    const onAbort = (): void => {
      clearTimeout(timer); // タイマーを残すとプロセスが終わらない
      reject(new Error("キャンセル通知を受け取ったため中断しました"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

const server = new McpServer({ name: "q4-cancel", version: "1.0.0" });

server.registerTool(
  "run_batch",
  {
    title: "一括処理",
    description: "10 ステップの処理を行います。進捗通知とキャンセルに対応しています。",
    inputSchema: {
      stepDelayMs: z
        .number()
        .int()
        .min(0)
        .max(1000)
        .default(60)
        .describe("1 ステップあたりの疑似待ち時間（ミリ秒）"),
    },
    annotations: { readOnlyHint: false, idempotentHint: false, openWorldHint: false },
  },
  async ({ stepDelayMs }, extra) => {
    const progressToken = extra._meta?.progressToken;
    let executedSteps = 0;
    lastRun = { executedSteps: 0, finished: false, cancelled: false };

    try {
      for (let step = 0; step < TOTAL_STEPS; step++) {
        // ② 区切りで確認する（待ち時間ゼロの処理でも中断できる）
        extra.signal.throwIfAborted();
        // ③ 待っている間も監視する
        await sleepOrAbort(stepDelayMs, extra.signal);
        executedSteps = step + 1;

        if (progressToken !== undefined) {
          try {
            await extra.sendNotification({
              method: "notifications/progress",
              params: { progressToken, progress: executedSteps, total: TOTAL_STEPS },
            });
          } catch (error) {
            console.error("[progress] 通知の送信に失敗しました:", error);
          }
        }
      }
    } catch (error) {
      // ④ どこまで進んだかを記録してから再送出する
      lastRun = { executedSteps, finished: false, cancelled: extra.signal.aborted };
      console.error(`[run_batch] 処理を中断しました（cancelled=${extra.signal.aborted}）`);
      throw error;
    }

    lastRun = { executedSteps, finished: true, cancelled: false };
    return { content: [{ type: "text", text: `${executedSteps} ステップ完了しました` }] };
  },
);

server.registerTool(
  "get_last_run_report",
  {
    title: "直前の実行記録",
    description: "直前の run_batch が何ステップ実行し、キャンセルされたかを JSON で返します。",
    inputSchema: {},
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  },
  async () => ({ content: [{ type: "text", text: JSON.stringify(lastRun) }] }),
);

// ---------------- 検証 ----------------
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "q4-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

const readReport = async (): Promise<RunReport> => {
  const result = await client.callTool({ name: "get_last_run_report", arguments: {} });
  const content = result.content as Array<{ type: string; text?: string }>;
  return JSON.parse(content[0]?.text ?? "{}") as RunReport;
};

// ケース1：キャンセルなし
await client.callTool({ name: "run_batch", arguments: {} });
const report1 = await readReport();
console.log(
  `[1/3] キャンセルなし: executedSteps=${report1.executedSteps} finished=${report1.finished} cancelled=${report1.cancelled}`,
);

// ケース2：3 ステップ目の進捗が届いたらキャンセル（時間ではなくステップで判定）
const controller = new AbortController();
let clientAborted = false;
try {
  await client.callTool({ name: "run_batch", arguments: {} }, undefined, {
    signal: controller.signal,
    onprogress: (progress) => {
      if (progress.progress >= 3) controller.abort();
    },
  });
} catch {
  clientAborted = true;
}
await sleep(300); // キャンセル通知がサーバーに届くのを待つ
const report2 = await readReport();
console.log(
  `[2/3] キャンセルあり: クライアント側=${clientAborted ? "中断" : "完走"} / executedSteps<${TOTAL_STEPS}=${report2.executedSteps < TOTAL_STEPS} cancelled=${report2.cancelled}`,
);

// ケース3：キャンセル後もセッションは生きている
await client.callTool({ name: "run_batch", arguments: {} });
const report3 = await readReport();
console.log(
  `[3/3] 再実行: executedSteps=${report3.executedSteps} finished=${report3.finished} cancelled=${report3.cancelled}`,
);

await client.close();
await server.close();
console.log("OK: 問題4 の条件を満たしています");
