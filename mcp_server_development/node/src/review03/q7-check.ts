/**
 * 問題7 の解答 ―― HTTP 経由で進捗通知が届くかを数える
 *
 *   docker compose exec node npx tsx src/review03/q7-check.ts SSEモード
 *   docker compose exec node npx tsx src/review03/q7-check.ts JSONモード
 *
 * ラベルは表示のためだけに使います（サーバー側の設定は環境変数で決まります）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const label = process.argv[2] ?? "(ラベルなし)";
const transport = new StreamableHTTPClientTransport(new URL("http://127.0.0.1:3939/mcp"));
const client = new Client({ name: "review03-q7-client", version: "1.0.0" });

await client.connect(transport);

let received = 0;
const result = await client.callTool(
  { name: "scan_documents", arguments: { perDocDelayMs: 40 } },
  undefined,
  {
    onprogress: () => {
      received += 1;
    },
  },
);
const scanned = (result.structuredContent as { scanned: number }).scanned;
console.log(`[${label}] 進捗通知=${received}回 / 走査=${scanned}件 / 完走=${scanned === 5}`);

// セッションを残さない（上限 4 件なので、残すと 4 回目以降が 503 になる）
await transport.terminateSession();
await client.close();
