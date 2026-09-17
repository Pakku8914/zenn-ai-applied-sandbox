/**
 * MCP サーバーの組み立て（ファクトリ関数）
 *
 * トランスポートへの接続をここでは行わないのが要点です。
 * サーバーの「中身」と「つなぎ先」を分けておくと、
 *   - 本番（stdio / HTTP）: src/server.ts から接続する
 *   - テスト（インメモリ）: src/server.test.ts から接続する
 * と、同じサーバー定義を使い回せます。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function createServer(): McpServer {
  const server = new McpServer({
    name: "sandbox-server",
    version: "1.0.0",
  });

  server.registerTool(
    "add",
    {
      title: "加算",
      description: "2 つの数値を足し合わせて結果を返します。",
      inputSchema: {
        a: z.number().describe("足される数"),
        b: z.number().describe("足す数"),
      },
    },
    async ({ a, b }) => ({
      content: [{ type: "text", text: `${a} + ${b} = ${a + b}` }],
    }),
  );

  return server;
}
