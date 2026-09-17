/**
 * サンドボックスの疎通確認スクリプト（TypeScript）
 *
 * MCP クライアントとして src/server.ts を子プロセスで起動し、
 *   1. initialize ハンドシェイク
 *   2. tools/list（ツール一覧の取得）
 *   3. tools/call（ツールの呼び出し）
 * が成功することを確認します。
 *
 * 実行： docker compose exec node npm run smoke
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/server.ts"],
});

const client = new Client({ name: "smoke-client", version: "1.0.0" });

await client.connect(transport);

const serverInfo = client.getServerVersion();
console.log(`[1/3] 接続成功: ${serverInfo?.name} v${serverInfo?.version}`);

const { tools } = await client.listTools();
console.log(`[2/3] tools/list: ${tools.map((t) => t.name).join(", ")}`);

const result = await client.callTool({
  name: "add",
  arguments: { a: 2, b: 3 },
});
const first = (result.content as Array<{ type: string; text?: string }>)[0];
console.log(`[3/3] tools/call: ${first?.text}`);

await client.close();
console.log("OK: サンドボックスは正常に動作しています");
