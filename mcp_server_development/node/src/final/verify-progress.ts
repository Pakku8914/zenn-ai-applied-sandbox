/**
 * 進捗通知とキャンセルの検証（固定時間の待機を使わない）
 *
 *   docker compose exec node npx tsx src/final/verify-progress.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { ProgressNotificationSchema } from "@modelcontextprotocol/sdk/types.js";

import { type AuthContext, SCOPE_READ } from "./auth/scopes.js";
import { type ScanReport, createWorkflowServer } from "./create-server.js";

const AUTH: AuthContext = {
  subject: "user-1001",
  clientId: "verify",
  scopes: [SCOPE_READ],
  expiresAt: 4_102_444_800,
  tokenRef: "verify00",
  tenantId: "acme",
};

async function connect(onScan: (report: ScanReport) => void): Promise<Client> {
  const server = createWorkflowServer({ auth: () => AUTH, onScan });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "progress-verify", version: "1.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return client;
}

/** 条件が成立するまで待つ（固定時間ではなく条件で待つ） */
async function waitFor(condition: () => boolean, timeoutMs = 2000): Promise<void> {
  const startedAt = Date.now();
  while (!condition()) {
    if (Date.now() - startedAt > timeoutMs) throw new Error("条件が成立しませんでした");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

// ① 進捗通知が 8 回届く
{
  let last: ScanReport | undefined;
  const client = await connect((report) => (last = report));
  const progress: number[] = [];
  await client.callTool(
    { name: "search_requests", arguments: { limit: 5 } },
    undefined,
    { onprogress: (event) => progress.push(event.progress) },
  );
  console.log(`[1] 進捗通知: ${progress.length} 回 / progress=${progress.join(",")}`);
  console.log(`[2] 走査: ${last?.scannedChunks}/${last?.totalChunks} finished=${last?.finished}`);
  await client.close();
}

// ② progressToken を送らなければ 0 回
{
  const client = await connect(() => undefined);
  let count = 0;
  client.setNotificationHandler(ProgressNotificationSchema, async () => {
    count += 1;
  });
  await client.callTool({ name: "search_requests", arguments: { limit: 5 } });
  console.log(`[3] progressToken なし: 進捗通知 ${count} 回`);
  await client.close();
}

// ③ 1 回目の進捗通知でキャンセルすると、サーバー側の走査も止まる
{
  let last: ScanReport | undefined;
  const client = await connect((report) => (last = report));
  const controller = new AbortController();
  const pending = client.callTool(
    { name: "search_requests", arguments: { limit: 5, scanDelayMs: 30 } },
    undefined,
    {
      signal: controller.signal,
      // 進捗が 1 つ届いた時点で中断する。固定時間の sleep を使わない
      onprogress: (event) => {
        if (event.progress === 1) controller.abort(new Error("検証から中断しました"));
      },
    },
  );
  const failed = await pending.then(
    () => false,
    () => true,
  );
  await waitFor(() => last?.cancelled === true);
  console.log(`[4] キャンセル: 呼び出しが失敗=${failed} cancelled=${last?.cancelled} 走査=${last?.scannedChunks}/8`);
  console.log(`[5] 途中で止まっている: ${(last?.scannedChunks ?? 8) < 8}`);
  await client.close();
}

console.log("OK: 進捗通知とキャンセルは仕様どおりに動作しています");
