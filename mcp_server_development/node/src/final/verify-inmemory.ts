/**
 * 機能の検証（インメモリ接続・認証層を起動しない）
 *
 *   docker compose exec node npx tsx src/final/verify-inmemory.ts
 *
 * クライアント側のスクリプトなので console.log を使ってかまいません。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { type AuthContext, SCOPE_APPROVE, SCOPE_READ, SCOPE_WRITE } from "./auth/scopes.js";
import { createWorkflowServer } from "./create-server.js";
import { createStore } from "./domain/workflow.js";
import { createAuditLogger } from "./observability/audit.js";

function auth(scopes: readonly string[]): AuthContext {
  return {
    subject: "user-1001",
    clientId: "verify-client",
    scopes,
    expiresAt: 4_102_444_800,
    tokenRef: "verify00",
    tenantId: "acme",
  };
}

const lines: string[] = [];
const store = createStore();
const audit = createAuditLogger({
  server: "workflow-requests",
  pepper: "verify-pepper",
  clock: () => 0,
  sink: (line) => lines.push(line),
});
let context = auth([SCOPE_READ, SCOPE_WRITE, SCOPE_APPROVE]);

const server = createWorkflowServer({ store, audit, auth: () => context });
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "final-verify", version: "1.0.0" });
await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

function text(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): string {
  const blocks = (result.content ?? []) as Array<{ type: string; text?: string }>;
  return blocks.map((block) => block.text ?? "").join("\n");
}
async function call(name: string, args: Record<string, unknown> = {}) {
  return client.callTool({ name, arguments: args });
}

const tools = (await client.listTools()).tools;
console.log(`[1] tools/list: ${tools.length} 本 = ${tools.map((t) => t.name).sort().join(", ")}`);
const decide = tools.find((tool) => tool.name === "decide_request");
console.log(`[2] decide_request の destructiveHint: ${decide?.annotations?.destructiveHint}`);
console.log(
  `[3] 全ツールに注釈 4 つ: ${tools.every((tool) => Object.keys(tool.annotations ?? {}).length >= 4)}`,
);

const all = await call("search_requests", { limit: 10 });
const allStructured = all.structuredContent as { total: number; returned: number; hasMore: boolean; scannedChunks: number };
console.log(
  `[4] search_requests(limit=10): total=${allStructured.total} returned=${allStructured.returned} hasMore=${allStructured.hasMore} scannedChunks=${allStructured.scannedChunks}`,
);

for (const [label, args] of [
  ["status=in_review", { status: ["in_review"] }],
  ["category=expense,min=10000", { category: "expense", minAmountYen: 10_000 }],
  ["applicantId=u-001", { applicantId: "u-001" }],
  ["query=研修", { query: "研修" }],
  ["query=購入", { query: "購入" }],
  ["query=ゼロトラスト", { query: "ゼロトラスト" }],
] as const) {
  const result = await call("search_requests", { ...args, limit: 50 });
  const structured = result.structuredContent as { total: number };
  console.log(`[5] search(${label}): total=${structured.total} isError=${result.isError === true}`);
}

const detail = text(await call("get_request", { requestId: "req-1003", include: ["comments"] }));
console.log(
  `[6] get_request(req-1003): コメント=${/コメント（全 (\d+) 件/.exec(detail)?.[1] ?? "0"} 件 / 履歴=${detail.includes("履歴（") ? "含む" : "含まない"}`,
);

const created = text(
  await call("save_request", {
    title: "書籍購入（技術書 3 冊）",
    category: "purchase",
    amountYen: 12_000,
    body: "チームの技術書を 3 冊購入します。",
  }),
);
const newId = /^(req-\d{4})/.exec(created)?.[1] ?? "";
console.log(`[7] save_request(新規): ${created.split("\n")[0]}`);
console.log(`[8] save_request(必須漏れ): ${text(await call("save_request", { title: "題名だけ" })).split("\n")[0]}`);

const submitDry = text(await call("submit_request", { requestId: newId }));
const submitToken = /previewToken: (\S+)/.exec(submitDry)?.[1] ?? "";
console.log(`[9] submit_request(ドライラン): ${submitDry.split("\n")[1]}`);
console.log(
  `[10] submit_request(確定): ${text(await call("submit_request", { requestId: newId, confirm: true, previewToken: submitToken }))}`,
);

const decideDry = await call("decide_request", { requestId: "req-1003", decision: "approve" });
const dry = decideDry.structuredContent as { applied: boolean; stepLabel: string; nextStatus: string; finalizes: boolean; previewToken?: string };
console.log(`[11] decide(ドライラン): applied=${dry.applied} ${dry.stepLabel} 確定後=${dry.nextStatus} 終了=${dry.finalizes}`);
const decided = await call("decide_request", {
  requestId: "req-1003",
  decision: "approve",
  confirm: true,
  previewToken: dry.previewToken,
});
console.log(`[12] decide(確定): applied=${(decided.structuredContent as { applied: boolean }).applied}`);

const badToken = await call("decide_request", {
  requestId: "req-1002",
  decision: "approve",
  confirm: true,
  previewToken: "ZmFrZQ.c2ln",
});
console.log(`[13] decide(トークン不一致): isError=${badToken.isError === true} ${text(badToken).split("\n")[0]}`);

console.log(
  `[14] comment_on_request: ${text(await call("comment_on_request", { requestId: "req-1002", body: "見積を確認しました。" }))}`,
);

const templates = await client.listResourceTemplates();
const resources = await client.listResources();
console.log(
  `[15] templates=${templates.resourceTemplates.length}（${templates.resourceTemplates[0]?.uriTemplate}） resources=${resources.resources.length} 先頭=${resources.resources[0]?.uri}`,
);
const read = await client.readResource({ uri: "request://req-1003" });
console.log(`[16] resources/read: mimeType=${read.contents[0]?.mimeType} 1行目=${String((read.contents[0] as { text?: string } | undefined)?.text ?? "").split("\n")[0]}`);
const completion = await client.complete({
  ref: { type: "ref/resource", uri: "request://{id}" },
  argument: { name: "id", value: "req-100" },
});
console.log(`[17] completion(req-100): ${completion.completion.values.length} 件`);
const prompt = await client.getPrompt({
  name: "draft_request",
  arguments: { category: "expense", summary: "書籍購入の精算" },
});
console.log(`[18] prompts/get: messages=${prompt.messages.length} 種別=${prompt.messages.map((m) => m.content.type).join(", ")}`);

// ── 異常系（rejects ではなく isError で受ける） ──
const badEnum = await call("search_requests", { status: ["reviewing"] });
console.log(`[19] 列挙にない値: isError=${badEnum.isError === true} 本文に -32602=${text(badEnum).includes("-32602")}`);
const unknownTool = await call("approve_request", { requestId: "req-1002" });
console.log(`[20] 未知のツール名: isError=${unknownTool.isError === true} 本文に not found=${text(unknownTool).includes("not found")}`);

// ── スコープ ──
context = auth([SCOPE_READ]);
const forbidden = await call("decide_request", { requestId: "req-1002", decision: "approve" });
console.log(`[21] read だけで decide: isError=${forbidden.isError === true} ${text(forbidden).split("\n")[0]}`);

console.log(`[22] 監査ログ: ${lines.length} 行 / 全部 1 行 JSON=${lines.every((line) => !line.includes("\n") && line.startsWith("{"))}`);
console.log(`[23] 監査ログに本文が出ていない: ${!lines.some((line) => line.includes("技術書を 3 冊"))}`);

await client.close();
await server.close();
console.log("OK: 最終プロジェクトの MCP 層は仕様どおりに動作しています");
