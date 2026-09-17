/**
 * 失敗の 3 層を実際に観測する
 *
 * 実行： docker compose exec node npx tsx src/session11/layer-demo.ts
 *
 *   層1 トランスポート : 子プロセスが起動できない／起動直後に落ちる（stdio で再現）
 *   層2 JSON-RPC       : error オブジェクトが返る（クライアントでは例外になる）
 *   層3 ツール実行     : isError: true のツール結果が返る（モデルが読める）
 *
 * クライアント側のスクリプトなので console.log を使ってかまいません
 * （禁止されているのは「サーバープロセスの stdout」だけです）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { EmptyResultSchema, McpError } from "@modelcontextprotocol/sdk/types.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { createWorkflowServer } from "./create-server.js";
import { createBudgetApi } from "./fixtures.js";

/** 例外を「どの層の失敗か」が分かる 1 行に変換する */
function describe(error: unknown): string {
  if (error instanceof McpError) {
    return `McpError code=${error.code} / ${error.message.slice(0, 70)}`;
  }
  if (error instanceof Error) return `${error.name} / ${error.message.slice(0, 70)}`;
  return String(error);
}

// ── 層1: トランスポート層 ───────────────────────────────────────────────
// サーバー定義の中身とは無関係に、通信路そのものが成立しないケースです。
async function transportCase(label: string, command: string, args: string[]): Promise<void> {
  const client = new Client({ name: "layer-demo", version: "1.0.0" });
  const transport = new StdioClientTransport({ command, args });
  // 応答が返らないまま待ち続けるのを避けるため、自前の時間切れを用意します
  const timeout = new Promise<string>((resolve) => {
    setTimeout(() => resolve("5 秒待っても応答がありません（時間切れ）"), 5000).unref();
  });
  const attempt = client
    .connect(transport)
    .then(() => "接続できてしまいました")
    .catch((error: unknown) => describe(error));
  console.log(`[層1] ${label}: ${await Promise.race([attempt, timeout])}`);
  await client.close().catch(() => undefined);
}

await transportCase("サーバーを起動できない", "no-such-mcp-server", []);
await transportCase("起動直後に落ちる", "node", ["-e", "process.exit(1)"]);

// ── 層2・層3: インメモリで観測する ─────────────────────────────────────
async function connect(server: McpServer, label: string): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: `layer-demo-${label}`, version: "1.0.0" });
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  return client;
}

const client = await connect(createWorkflowServer().server, "main");

/** 層2 の観測：例外として返ってくるものを捕まえる */
async function protocolCase(label: string, run: () => Promise<unknown>): Promise<void> {
  try {
    await run();
    console.log(`[層2] ${label}: エラーになりませんでした`);
  } catch (error) {
    console.log(`[層2] ${label}: ${describe(error)}`);
  }
}

await protocolCase("存在しないメソッド", () =>
  // MCP が知らないメソッド名。クライアントは検証せずサーバーへ送ります
  client.request({ method: "workflow/nonexistent", params: {} }, EmptyResultSchema),
);
await protocolCase("存在しないツール名", () =>
  // セッション10 の Bad 実装にあった名前。Good 実装には存在しません
  client.callTool({ name: "approve_request", arguments: { id: "req-1003" } }),
);
await protocolCase("列挙型に無い値", () =>
  client.callTool({ name: "search_requests", arguments: { status: ["審査中"] } }),
);

/** 層3 の観測：ツール結果として返ってくるものを読む */
async function toolCase(
  label: string,
  target: Client,
  name: string,
  args: Record<string, unknown>,
): Promise<void> {
  const result = await target.callTool({ name, arguments: args });
  const first = (result.content as Array<{ text?: string }> | undefined)?.[0];
  const text = first?.text ?? "";
  const code = /^\[(\w+)\]/.exec(text)?.[1] ?? "-";
  const retry = text.includes("再試行: 不可") ? "不可" : "可";
  const structured = (result.structuredContent as { error?: unknown } | undefined)?.error;
  console.log(
    `[層3] ${label}: isError=${result.isError === true} code=${code} 再試行=${retry} ` +
      `構造化エラー=${structured === undefined ? "なし" : "あり"}`,
  );
}

await toolCase("対象が存在しない", client, "get_request", { requestId: "req-9999" });
await toolCase("状態が前提を満たさない", client, "submit_request", { requestId: "req-1004" });
await toolCase("引数が業務的にありえない", client, "decide_request", {
  requestId: "req-1002",
  decision: "reject",
});

// 外部システムが落ちている状況を再現したサーバー
const flakyClient = await connect(
  createWorkflowServer({ budgetApi: createBudgetApi({ failures: 1 }) }).server,
  "flaky",
);
await toolCase("外部システムが落ちている", flakyClient, "submit_request", {
  requestId: "req-1001",
});

// 読み取り権限しか持たないセッションを再現したサーバー
const readOnlyClient = await connect(
  createWorkflowServer({ grantedScopes: ["requests:read"] }).server,
  "readonly",
);
await toolCase("権限がない", readOnlyClient, "decide_request", {
  requestId: "req-1002",
  decision: "approve",
});

console.log("OK: 3 層の違いを観測しました");
