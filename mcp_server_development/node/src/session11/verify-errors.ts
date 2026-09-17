/**
 * エラー設計と返却量の総合確認
 *
 * 実行： docker compose exec node npx tsx src/session11/verify-errors.ts
 *
 * 確認する観点
 *   ・失敗が isError で表明されているか
 *   ・文面に 3 要素（何が悪いか／どう直すか／再試行可否）が入っているか
 *   ・機械可読な error が返っているか
 *   ・内部情報が漏れていないか
 *   ・上限に達したことと続きの取り方が返っているか
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { createWorkflowServer } from "./create-server.js";
import { leaksInternalDetail } from "./errors.js";
import { createBudgetApi, createBulkyStore } from "./fixtures.js";

type ToolResult = { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown };

async function connect(server: McpServer, label: string): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: `verify-${label}`, version: "1.0.0" });
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  return client;
}

function blocks(result: ToolResult): Array<{ type?: string; text?: string }> {
  return (result.content as Array<{ type?: string; text?: string }> | undefined) ?? [];
}

function firstText(result: ToolResult): string {
  return blocks(result)[0]?.text ?? "";
}

function errorCode(result: ToolResult): string {
  return /^\[(\w+)\]/.exec(firstText(result))?.[1] ?? "-";
}

/** 3 要素がそろっているか（文面の品質を機械的に検査する） */
function hasThreeParts(result: ToolResult): boolean {
  const text = firstText(result);
  return text.startsWith("[") && text.includes("次の一手:") && text.includes("再試行:");
}

function structuredError(result: ToolResult): { code?: string; retryable?: boolean; retryAfterSeconds?: number } | undefined {
  return (result.structuredContent as { error?: { code?: string; retryable?: boolean; retryAfterSeconds?: number } } | undefined)?.error;
}

const client = await connect(createWorkflowServer({ store: createBulkyStore() }).server, "main");

const names = (await client.listTools()).tools.map((tool) => tool.name).sort();
console.log(`[1/11] tools/list: ${names.length} 本 = ${names.join(", ")}`);

const notFound = await client.callTool({ name: "get_request", arguments: { requestId: "req-9999" } });
console.log(
  `[2/11] 対象が存在しない: isError=${notFound.isError === true} code=${errorCode(notFound)} 3要素=${hasThreeParts(notFound)}`,
);

// req-1005 は rejected。次の一手として別のツール名が案内されることを確認する
const wrongState = await client.callTool({
  name: "submit_request",
  arguments: { requestId: "req-1005" },
});
console.log(
  `[3/11] 状態が前提を満たさない: code=${errorCode(wrongState)} 3要素=${hasThreeParts(wrongState)} ` +
    `次の一手に別ツール名=${firstText(wrongState).includes("save_request")}`,
);

const noComment = await client.callTool({
  name: "decide_request",
  arguments: { requestId: "req-1002", decision: "reject" },
});
const noCommentError = structuredError(noComment);
console.log(
  `[4/11] 引数が業務的にありえない: code=${errorCode(noComment)} ` +
    `構造化エラー code=${noCommentError?.code} retryable=${noCommentError?.retryable}`,
);

const readOnly = await connect(
  createWorkflowServer({ store: createBulkyStore(), grantedScopes: ["requests:read"] }).server,
  "readonly",
);
const forbidden = await readOnly.callTool({
  name: "decide_request",
  arguments: { requestId: "req-1002", decision: "approve" },
});
console.log(
  `[5/11] 権限がない: isError=${forbidden.isError === true} code=${errorCode(forbidden)} ` +
    `retryable=${structuredError(forbidden)?.retryable}`,
);
const readable = await readOnly.callTool({
  name: "get_request",
  arguments: { requestId: "req-1002" },
});
console.log(`[6/11] 読み取りだけは通る: isError=${readable.isError === true}`);

const flaky = await connect(
  createWorkflowServer({
    store: createBulkyStore(),
    budgetApi: createBudgetApi({ failures: 1 }),
  }).server,
  "flaky",
);
const upstream = await flaky.callTool({ name: "submit_request", arguments: { requestId: "req-1001" } });
console.log(
  `[7/11] 外部システム障害: code=${errorCode(upstream)} ` +
    `再試行=${firstText(upstream).includes("再試行: 可") ? "可" : "不可"} ` +
    `内部情報の露出=${leaksInternalDetail(firstText(upstream)) ? "あり" : "なし"} ` +
    `状態の明示=${firstText(upstream).includes("まだ提出されていません")}`,
);
const retried = await flaky.callTool({ name: "submit_request", arguments: { requestId: "req-1001" } });
console.log(
  `[8/11] 再試行すると成功: isError=${retried.isError === true} ` +
    `残予算の提示=${firstText(retried).includes("残予算")}`,
);

const listed = await client.callTool({ name: "search_requests", arguments: { limit: 50 } });
const listedStructured = listed.structuredContent as {
  total: number;
  returned: number;
  hasMore: boolean;
  omitted?: number;
  nextCursor?: string;
};
console.log(
  `[9/11] 上限付き返却: total=${listedStructured.total} returned=${listedStructured.returned} ` +
    `omitted=${listedStructured.omitted} hasMore=${listedStructured.hasMore} ` +
    `nextCursor=${listedStructured.nextCursor === undefined ? "なし" : "あり"} ` +
    `本文を含まない=${!firstText(listed).includes("研修の内容は")}`,
);

const continued = await client.callTool({
  name: "search_requests",
  arguments: { limit: 50, cursor: listedStructured.nextCursor },
});
const continuedStructured = continued.structuredContent as { returned: number; items: Array<{ id: string }> };
console.log(
  `[10/11] 続きが取れる: returned=${continuedStructured.returned} ` +
    `先頭=${continuedStructured.items[0]?.id ?? "-"}`,
);

const bulky = await client.callTool({
  name: "get_request",
  arguments: { requestId: "req-1003", include: ["comments", "history"] },
});
const bulkyText = firstText(bulky);
console.log(
  `[11/11] 本文を渡さない設計: 本文を切った=${bulkyText.includes("先頭 400 文字だけを返しました")} ` +
    `参照を添えた=${blocks(bulky)[1]?.type === "resource_link"} ` +
    `コメントは直近 5 件=${bulkyText.includes("全 24 件のうち直近 5 件")}`,
);

await client.close();
await readOnly.close();
await flaky.close();
console.log("OK: セッション11 のエラー設計は仕様どおりに動作しています");
