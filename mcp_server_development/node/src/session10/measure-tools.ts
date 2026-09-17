/**
 * Bad（18 本）と Good（6 本）を比較する計測スクリプト
 *
 * 実行： docker compose exec node npx tsx src/session10/measure-tools.ts
 *
 * 測るもの
 *   1. ツール定義の合計サイズ（毎ターンの固定費）
 *   2. 同じ用件を片付けるための呼び出し回数と返却量（都度の変動費）
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { createMirroredServer } from "./bad-create-server.js";
import { createWorkflowServer } from "./good-create-server.js";
import { breakdown, estimateTokens, measureTools, type Measured } from "./tokens.js";

async function connect(server: McpServer, label: string): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: `measure-${label}`, version: "1.0.0" });
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  return client;
}

function printTable(label: string, measured: Measured): void {
  console.log(`\n[${label}] ツール ${measured.rows.length} 本`);
  console.log(`  ${"name".padEnd(20)}${"chars".padStart(8)}${"~tokens".padStart(9)}`);
  for (const row of measured.rows) {
    console.log(
      `  ${row.name.padEnd(20)}${String(row.chars).padStart(8)}${String(row.tokens).padStart(9)}`,
    );
  }
  console.log(
    `  ${"合計".padEnd(19)}${String(measured.totalChars).padStart(8)}${String(measured.totalTokens).padStart(9)}`,
  );
}

/** ツール結果の大きさ（AI のコンテキストに載る量）を数える */
function resultSize(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): number {
  const content = JSON.stringify(result.content ?? []);
  const structured =
    result.structuredContent === undefined ? "" : JSON.stringify(result.structuredContent);
  return content.length + structured.length;
}

/** 用件：「req-1003 を承認していいか判断して、問題なければ承認する」 */
async function runBadScenario(client: Client): Promise<{ calls: number; chars: number }> {
  const calls = [
    { name: "get_request_detail", arguments: { id: "req-1003" } },
    { name: "list_comments", arguments: { id: "req-1003" } },
    { name: "list_attachments", arguments: { id: "req-1003" } },
    { name: "list_approvals", arguments: { id: "req-1003" } },
    { name: "approve_request", arguments: { id: "req-1003", comment: "内容を確認しました。" } },
  ];
  let chars = 0;
  for (const call of calls) {
    chars += resultSize(await client.callTool(call));
  }
  return { calls: calls.length, chars };
}

async function runGoodScenario(client: Client): Promise<{ calls: number; chars: number }> {
  let chars = 0;
  const detail = await client.callTool({
    name: "get_request",
    arguments: { requestId: "req-1003", include: ["comments", "attachments"] },
  });
  chars += resultSize(detail);

  const dry = await client.callTool({
    name: "decide_request",
    arguments: { requestId: "req-1003", decision: "approve", comment: "内容を確認しました。" },
  });
  chars += resultSize(dry);
  const token = (dry.structuredContent as { previewToken?: string }).previewToken;

  const applied = await client.callTool({
    name: "decide_request",
    arguments: {
      requestId: "req-1003",
      decision: "approve",
      comment: "内容を確認しました。",
      confirm: true,
      previewToken: token,
    },
  });
  chars += resultSize(applied);
  return { calls: 3, chars };
}

/** 減少なら -、増加なら + を付けて返す（増えた場合に「--6.6%」にならないように） */
function rate(before: number, after: number): string {
  const change = ((before - after) / before) * 100;
  return `${change >= 0 ? "-" : "+"}${Math.abs(change).toFixed(1)}%`;
}

const badClient = await connect(createMirroredServer(), "bad");
const goodClient = await connect(createWorkflowServer().server, "good");

const bad = measureTools((await badClient.listTools()).tools);
const good = measureTools((await goodClient.listTools()).tools);

console.log("=== 1. ツール定義のサイズ（毎ターンの固定費）===");
printTable("bad: 18 本を機械的に写した設計", bad);
printTable("good: 意図ベースの 6 ツール", good);

console.log("\n=== 2. 差分 ===");
console.log(`  ツール本数   : ${bad.rows.length} → ${good.rows.length}（${rate(bad.rows.length, good.rows.length)}）`);
console.log(`  定義の文字数 : ${bad.totalChars} → ${good.totalChars}（${rate(bad.totalChars, good.totalChars)}）`);
console.log(`  概算トークン : ${bad.totalTokens} → ${good.totalTokens}（${rate(bad.totalTokens, good.totalTokens)}）`);
console.log(
  `  1 本あたり   : ${Math.round(bad.totalChars / bad.rows.length)} chars → ` +
    `${Math.round(good.totalChars / good.rows.length)} chars（説明と outputSchema を厚くした分）`,
);

console.log("\n=== 3. 同じ用件を片付けるコスト（都度の変動費）===");
const badRun = await runBadScenario(badClient);
const goodRun = await runGoodScenario(goodClient);
console.log(`  bad : ${badRun.calls} 回呼び出し / 返却 ${badRun.chars} chars（約 ${estimateTokens("x".repeat(badRun.chars))} tokens 相当の枠）`);
console.log(`  good: ${goodRun.calls} 回呼び出し / 返却 ${goodRun.chars} chars`);
console.log(`  返却量の削減 : ${rate(badRun.chars, goodRun.chars)}`);

console.log("\n=== 4. good の 1 本を部位ごとに分解（どこが太っているか）===");
const searchTool = (await goodClient.listTools()).tools.find(
  (tool) => tool.name === "search_requests",
);
if (searchTool !== undefined) {
  for (const [part, chars] of Object.entries(breakdown(searchTool as Record<string, unknown>))) {
    console.log(`  ${part.padEnd(14)}${String(chars).padStart(6)} chars`);
  }
}

await badClient.close();
await goodClient.close();
