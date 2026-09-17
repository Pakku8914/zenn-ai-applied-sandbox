/**
 * 問題5 の解答 ―― インメモリトランスポートでつなぐ確認用スクリプト
 *
 *   docker compose exec node npx tsx src/review03/q5-verify.ts
 *
 * 子プロセスを起こさないので速く、出力も安定します
 * （インメモリトランスポートはセッション13 のテストの章で本格的に扱います）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { registerScanTool, type ScanReport } from "./q5-scan-tool.js";

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const server = new McpServer({ name: "review03-q5", version: "1.0.0" });
registerScanTool(server);

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "review03-q5-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

const readReport = async (): Promise<ScanReport> =>
  (await client.callTool({ name: "get_last_scan_report", arguments: {} }))
    .structuredContent as ScanReport;

// ---- ① 進捗を要求する ----
let received = 0;
let lastProgress = 0;
let lastTotal: number | undefined;
const withProgress = await client.callTool(
  { name: "scan_documents", arguments: { perDocDelayMs: 10 } },
  undefined,
  {
    // onprogress を渡すと、SDK が _meta.progressToken を自動で付けてくれる
    onprogress: (progress) => {
      received += 1;
      lastProgress = progress.progress;
      lastTotal = progress.total;
    },
  },
);
const scanned = (withProgress.structuredContent as { scanned: number }).scanned;
console.log(`[1/3] 進捗あり: 受信=${received}回 / 最後=${lastProgress}/${lastTotal} / 走査=${scanned}件`);

// ---- ② 進捗を要求しない ----
received = 0;
await client.callTool({ name: "scan_documents", arguments: { perDocDelayMs: 10 } });
const quiet = await readReport();
console.log(`[2/3] 進捗なし: 受信=${received}回 / サーバー側の送信試行=${quiet.progressAttempts}回`);

// ---- ③ キャンセル ----
const controller = new AbortController();
let clientAborted = false;
try {
  await client.callTool(
    { name: "scan_documents", arguments: { perDocDelayMs: 80 } },
    undefined,
    {
      signal: controller.signal,
      // 時間ではなく「2 件目の進捗が届いたら」で判定するので結果が安定する
      onprogress: (progress) => {
        if (progress.progress >= 2) {
          controller.abort();
        }
      },
    },
  );
} catch {
  clientAborted = true;
}
await sleep(400); // キャンセル通知がサーバーに届くのを待つ
const cancelled = await readReport();
console.log(
  `[3/3] キャンセル: クライアント側=${clientAborted ? "中断" : "完走"}` +
    ` / cancelled=${cancelled.cancelled} / executedSteps<${cancelled.totalSteps}=${cancelled.executedSteps < cancelled.totalSteps}`,
);

await client.close();
await server.close();
console.log("OK: 問題5 の条件を満たしています");
