/**
 * 冗長な JSON をそのまま返す実装（Bad）と、整形した実装（Good）の返却量を比べる
 *
 * 実行： docker compose exec node npx tsx src/session11/measure-responses.ts
 *
 * 尺度はセッション10 と同じ（文字数と概算トークン）。
 * ツールの粒度は両者で同じなので、差はすべて「返し方」から来ます。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { createVerboseServer } from "./bad-create-server.js";
import { createWorkflowServer } from "./create-server.js";
import { leaksInternalDetail } from "./errors.js";
import { createBudgetApi, createBulkyStore } from "./fixtures.js";
import { responseSize, type ResponseSize } from "./respond.js";

type ToolResult = { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown };
type Row = { label: string; size: ResponseSize };

async function connect(server: McpServer, label: string): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: `measure-${label}`, version: "1.0.0" });
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  return client;
}

function firstText(result: ToolResult): string {
  return (result.content as Array<{ text?: string }> | undefined)?.[0]?.text ?? "";
}

/**
 * 用件：「未処理の申請を眺めて、req-1003 を承認していいか判断し、承認する」
 * 途中で失敗するケースも 2 つ混ぜます（エラーの返し方も測るため）。
 */
async function scenario(
  client: Client,
  pickToken: (result: ToolResult) => string | undefined,
): Promise<Row[]> {
  const rows: Row[] = [];
  const record = (label: string, result: ToolResult): void => {
    rows.push({ label, size: responseSize(result) });
  };

  const searched = await client.callTool({ name: "search_requests", arguments: { limit: 50 } });
  record("1 search_requests(limit=50)", searched);

  const detail = await client.callTool({
    name: "get_request",
    arguments: { requestId: "req-1003", include: ["comments", "history"] },
  });
  record("2 get_request(コメント+履歴)", detail);

  const dry = await client.callTool({
    name: "decide_request",
    arguments: { requestId: "req-1003", decision: "approve" },
  });
  record("3 decide_request(ドライラン)", dry);

  const applied = await client.callTool({
    name: "decide_request",
    arguments: {
      requestId: "req-1003",
      decision: "approve",
      confirm: true,
      previewToken: pickToken(dry),
    },
  });
  record("4 decide_request(確定)", applied);

  const missing = await client.callTool({
    name: "get_request",
    arguments: { requestId: "req-9999" },
  });
  record("5 存在しない ID（失敗）", missing);

  const wrongState = await client.callTool({
    name: "submit_request",
    arguments: { requestId: "req-1004" },
  });
  record("6 提出できない状態（失敗）", wrongState);

  return rows;
}

function rate(before: number, after: number): string {
  const value = ((before - after) / before) * 100;
  return `${value >= 0 ? "-" : "+"}${Math.abs(value).toFixed(1)}%`;
}

const badClient = await connect(createVerboseServer({ store: createBulkyStore() }), "bad");
const goodClient = await connect(
  createWorkflowServer({ store: createBulkyStore() }).server,
  "good",
);

const badRows = await scenario(badClient, (result) => {
  // Bad は生の JSON を返すので、文字列から取り出す必要がある
  try {
    return (JSON.parse(firstText(result)) as { previewToken?: string }).previewToken;
  } catch {
    return undefined;
  }
});
const goodRows = await scenario(
  goodClient,
  (result) => (result.structuredContent as { previewToken?: string } | undefined)?.previewToken,
);

console.log("=== 1. 同じ用件を処理したときの返却量（文字数）===");
console.log(`  ${"手順".padEnd(30)}${"bad".padStart(9)}${"good".padStart(9)}${"削減".padStart(9)}`);
let badTotal = 0;
let goodTotal = 0;
let badTokens = 0;
let goodTokens = 0;
for (const [index, badRow] of badRows.entries()) {
  const goodRow = goodRows[index];
  if (goodRow === undefined) continue;
  badTotal += badRow.size.chars;
  goodTotal += goodRow.size.chars;
  badTokens += badRow.size.tokens;
  goodTokens += goodRow.size.tokens;
  console.log(
    `  ${badRow.label.padEnd(30)}${String(badRow.size.chars).padStart(9)}` +
      `${String(goodRow.size.chars).padStart(9)}` +
      `${rate(badRow.size.chars, goodRow.size.chars).padStart(9)}`,
  );
}
console.log(
  `  ${"合計（文字）".padEnd(28)}${String(badTotal).padStart(9)}${String(goodTotal).padStart(9)}` +
    `${rate(badTotal, goodTotal).padStart(9)}`,
);
console.log(
  `  ${"合計（概算トークン）".padEnd(24)}${String(badTokens).padStart(9)}` +
    `${String(goodTokens).padStart(9)}${rate(badTokens, goodTokens).padStart(9)}`,
);

console.log("\n=== 2. Good の内訳（content と structuredContent の二重掲載）===");
for (const row of goodRows) {
  console.log(
    `  ${row.label.padEnd(30)}content=${String(row.size.contentChars).padStart(6)} ` +
      `structured=${String(row.size.structuredChars).padStart(6)}`,
  );
}

console.log("\n=== 3. 失敗の返し方の差（外部システムが落ちている場合）===");
const badFlaky = await connect(
  createVerboseServer({ store: createBulkyStore(), budgetApi: createBudgetApi({ failures: 5 }) }),
  "bad-flaky",
);
const goodFlaky = await connect(
  createWorkflowServer({
    store: createBulkyStore(),
    budgetApi: createBudgetApi({ failures: 5 }),
  }).server,
  "good-flaky",
);
const badFail = await badFlaky.callTool({
  name: "submit_request",
  arguments: { requestId: "req-1001" },
});
const goodFail = await goodFlaky.callTool({
  name: "submit_request",
  arguments: { requestId: "req-1001" },
});
for (const [label, result] of [
  ["bad ", badFail],
  ["good", goodFail],
] as const) {
  const text = firstText(result);
  console.log(
    `  ${label}: isError=${String(result.isError === true).padEnd(5)} ` +
      `${String(responseSize(result).chars).padStart(5)} chars / ` +
      `内部情報の露出=${leaksInternalDetail(text) ? "あり" : "なし"}`,
  );
}

await badClient.close();
await goodClient.close();
await badFlaky.close();
await goodFlaky.close();
