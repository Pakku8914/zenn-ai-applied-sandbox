/**
 * モードに応じてツールを出し入れし、定義サイズの変化を測る
 *
 * 実行： docker compose exec node npx tsx src/session10/deferred-loading.ts
 *
 * registerTool の戻り値（ハンドル）の enable() / disable() を使います。
 * disable() したツールは tools/list に載らなくなり、
 * SDK が notifications/tools/list_changed を自動で送ります。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { ToolListChangedNotificationSchema } from "@modelcontextprotocol/sdk/types.js";

import { createWorkflowServer, type ToolName } from "./good-create-server.js";
import { measureTools } from "./tokens.js";

const { server, tools } = createWorkflowServer();
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "session10-deferred", version: "1.0.0" });

let listChangedCount = 0;
client.setNotificationHandler(ToolListChangedNotificationSchema, () => {
  listChangedCount++;
});

await server.connect(serverTransport);
await client.connect(clientTransport);

async function report(label: string, baselineChars?: number): Promise<number> {
  const measured = measureTools((await client.listTools()).tools);
  const diff =
    baselineChars === undefined
      ? ""
      : `（-${(((baselineChars - measured.totalChars) / baselineChars) * 100).toFixed(1)}%）`;
  console.log(
    `[${label.padEnd(14)}] ツール ${measured.rows.length} 本 / ` +
      `${measured.totalChars} chars / 約 ${measured.totalTokens} tokens${diff}`,
  );
  return measured.totalChars;
}

/** モードごとに公開するツール */
const MODES: Record<string, ToolName[]> = {
  applicant: ["search_requests", "get_request", "save_request", "submit_request", "comment_on_request"],
  approver: ["search_requests", "get_request", "decide_request"],
};

const baseline = await report("all");

for (const [mode, allowed] of Object.entries(MODES)) {
  for (const [name, handle] of Object.entries(tools)) {
    if (allowed.includes(name as ToolName)) handle.enable();
    else handle.disable();
  }
  await report(mode, baseline);
}

console.log(`notifications/tools/list_changed の受信回数: ${listChangedCount}`);
console.log(
  "※ 1 回のモード切り替えで複数回飛びます。まとめて送る（デバウンス）検討はセッション8 を参照してください。",
);

await client.close();
await server.close();
