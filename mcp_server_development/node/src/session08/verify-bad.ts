/**
 * 動作確認用クライアント（Bad 実装との対比）
 *
 * 実行： docker compose exec node npx tsx src/session08/verify-bad.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const client = new Client({ name: "session08-verify-bad", version: "1.0.0" });
await client.connect(
  new StdioClientTransport({ command: "npx", args: ["tsx", "src/session08/bad-server.ts"] }),
);

let progressCount = 0;
let clientAborted = false;
const controller = new AbortController();
setTimeout(() => controller.abort(), 300); // 進捗が来ないので時間で打ち切るしかない

try {
  await client.callTool(
    { name: "aggregate_observations", arguments: { chunkDelayMs: 120 } },
    undefined,
    { signal: controller.signal, onprogress: () => { progressCount += 1; } },
  );
} catch {
  clientAborted = true;
}
console.log(`[1/2] 進捗通知: 受信=${progressCount}回（要求しているのに送られてこない）`);

// Bad 実装は止まらないので、走り切るのを待ってから記録を読む
await sleep(3000);
const text = (await client.callTool({ name: "get_last_run_report", arguments: {} }))
  .content as Array<{ type: string; text?: string }>;
const report = JSON.parse(text[0]?.text ?? "{}") as { executedSteps: number; cancelled: boolean };
console.log(
  `[2/2] キャンセル: クライアント側=${clientAborted ? "中断" : "完走"} / サーバー側 cancelled=${report.cancelled} / executedSteps=${report.executedSteps}`,
);

await client.close();
console.log("NG: クライアントが諦めたあとも、サーバーは 20 ステップすべてを実行していました");
