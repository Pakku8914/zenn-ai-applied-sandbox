/**
 * Streamable HTTP でつなぐ検証用クライアント
 *
 *   docker compose exec node npx tsx src/session07/http-client.ts
 *   docker compose exec node npx tsx src/session07/http-client.ts http://127.0.0.1:3939/mcp
 *
 * クライアント側なので console.log を使ってかまいません。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

type SearchStructured = {
  totalMatched: number;
  returned: number;
  truncated: boolean;
  results: { path: string; score: number }[];
};

const url = new URL(process.argv[2] ?? "http://127.0.0.1:3939/mcp");
const transport = new StreamableHTTPClientTransport(url);
const client = new Client({ name: "session07-http-client", version: "1.0.0" });

await client.connect(transport);
const info = client.getServerVersion();
console.log(`[1/5] 接続: ${info?.name} v${info?.version} / URL=${url.href}`);
// セッション ID はトランスポートが応答ヘッダーから拾って保持している
console.log(`[2/5] Mcp-Session-Id: ${transport.sessionId ?? "(なし＝ステートレス運用)"}`);

const { tools } = await client.listTools();
console.log(`[3/5] tools/list: ${tools.map((tool) => tool.name).join(", ")}`);

const result = (await client.callTool({
  name: "search_documents",
  arguments: { query: "VPN", limit: 2 },
})) as { structuredContent?: SearchStructured };
const structured = result.structuredContent;
console.log(
  `[4/5] tools/call: totalMatched=${structured?.totalMatched} returned=${structured?.returned}` +
    ` truncated=${structured?.truncated} → ` +
    (structured?.results ?? []).map((hit) => `${hit.path}(${hit.score})`).join(", "),
);

// DELETE を送ってセッションを明示的に破棄する（送らないとサーバー側に残る）
await transport.terminateSession();
console.log(`[5/5] terminateSession 後の sessionId: ${transport.sessionId ?? "(破棄済み)"}`);
await client.close();
