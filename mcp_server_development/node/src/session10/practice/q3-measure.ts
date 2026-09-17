/**
 * 問題3 の解答：定義サイズの計測と削減見込みの算出
 *
 * 実行： docker compose exec node npx tsx src/session10/practice/q3-measure.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { createMirroredServer } from "../bad-create-server.js";
import { breakdown, measureTools } from "../tokens.js";

/** include に畳んだときに増える分の見積もり（仮定：120 chars） */
const INCLUDE_COST_CHARS = 120;

/** get_request_detail の include に吸収できる 4 本 */
const FOLDABLE = ["list_comments", "list_attachments", "list_history", "list_approvals"];

const server = createMirroredServer();
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "q3-measure", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

const tools = (await client.listTools()).tools;
const measured = measureTools(tools);

console.log(
  `[1/3] bad の合計: ${measured.rows.length} 本 / ${measured.totalChars} chars / 約 ${measured.totalTokens} tokens`,
);

const largest = [...measured.rows].sort((a, b) => b.chars - a.chars).slice(0, 3);
console.log(
  `[2/3] 大きい順 上位3: ${largest.map((row) => `${row.name}(${row.chars})`).join(", ")}`,
);

const foldedChars = measured.rows
  .filter((row) => FOLDABLE.includes(row.name))
  .reduce((sum, row) => sum + row.chars, 0);
const saved = foldedChars - INCLUDE_COST_CHARS;
console.log(
  `[3/3] 4 本を include に畳んだ場合: -${saved} chars（-${((saved / measured.totalChars) * 100).toFixed(1)}%）`,
);

// 「なぜ太っているか」を具体的に語るために、上位 1 本を部位ごとに分解する
const top = tools.find((tool) => tool.name === largest[0]?.name);
if (top !== undefined) {
  console.log(`\n[参考] ${top.name} の内訳:`);
  for (const [part, chars] of Object.entries(breakdown(top as Record<string, unknown>))) {
    console.log(`  ${part.padEnd(14)}${String(chars).padStart(6)} chars`);
  }
}

await client.close();
await server.close();
console.log("\nOK: 問題3 の計測が完了しました");
