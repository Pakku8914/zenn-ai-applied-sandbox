/**
 * JSON-RPC エラーを実際に発生させて、返ってくるコードを観察する
 *
 * SDK のクライアントは、サーバーから error オブジェクトを受け取ると
 * McpError という例外に変換して投げます。code と message をそのまま表示します。
 *
 * 実行： docker compose exec node npx tsx src/session02/error-probe.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import {
  CallToolResultSchema,
  McpError,
  type Request,
} from "@modelcontextprotocol/sdk/types.js";

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/server.ts"],
});
const client = new Client({ name: "error-probe", version: "1.0.0" });
await client.connect(transport);

/** 生のリクエストを 1 本投げて、成功なら結果、失敗ならコードを表示する */
async function probe(label: string, request: Request): Promise<void> {
  try {
    const result = await client.request(request, CallToolResultSchema);
    console.log(`${label}\n  → 成功: ${JSON.stringify(result)}`);
  } catch (error) {
    if (error instanceof McpError) {
      console.log(`${label}\n  → code=${error.code} message=${error.message}`);
    } else {
      console.log(`${label}\n  → MCP エラー以外の例外: ${String(error)}`);
    }
  }
}

await probe("① 存在しないメソッドを呼ぶ", {
  method: "tools/nonexistent",
  params: {},
});
await probe("② 存在しないツール名で tools/call", {
  method: "tools/call",
  params: { name: "subtract", arguments: { a: 1, b: 2 } },
});
await probe("③ 引数の型が違う（a に文字列）", {
  method: "tools/call",
  params: { name: "add", arguments: { a: "two", b: 3 } },
});
await probe("④ 必須引数が足りない（b が無い）", {
  method: "tools/call",
  params: { name: "add", arguments: { a: 1 } },
});
await probe("⑤ 正常系（比較用）", {
  method: "tools/call",
  params: { name: "add", arguments: { a: 1, b: 2 } },
});

await client.close();
