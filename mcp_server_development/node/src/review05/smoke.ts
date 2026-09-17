/**
 * 共通の土台の疎通確認
 *
 *   docker compose exec node npx tsx src/review05/smoke.ts
 *
 * クライアント側のスクリプトなので console.log を使ってかまいません
 * （サーバープロセスでは stdout が JSON-RPC の通信路になるので禁止です）。
 */
import { createGateServer } from "./gate-server.js";
import { callTool, connectInMemory, digestTools, toolText } from "./harness.js";

const client = await connectInMemory(
  createGateServer({
    scopes: ["requests:read", "requests:approve"],
    nonce: () => "deadbeefdeadbeef",
    audit: () => {}, // 疎通確認では監査ログを捨てる
  }),
);

const { tools } = await client.listTools();
console.log(`ツール ${tools.length} 本: ${digestTools(tools).map((tool) => tool.name).join(", ")}`);

const searched = await callTool(client, "search_requests", { query: "購入" });
console.log(toolText(searched).split("\n")[0] ?? "");

const dryRun = await callTool(client, "decide_request", { id: "req-1001", decision: "approve" });
console.log(toolText(dryRun).split("\n")[0] ?? "");

await client.close();
