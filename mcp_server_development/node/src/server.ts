/**
 * 最小の MCP サーバー（TypeScript / stdio トランスポート）のエントリーポイント
 *
 * サンドボックスが正しく動くことを確認するための「Hello, World」相当のサーバーです。
 *
 * 重要：stdio トランスポートでは標準出力（stdout）が JSON-RPC の通信路そのものです。
 * console.log で何か書くと電文が壊れます。ログは必ず標準エラー出力（stderr）へ。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createServer } from "./create-server.js";

const server = createServer();
const transport = new StdioServerTransport();
await server.connect(transport);

// ログは stderr へ。stdout は JSON-RPC 専用なので絶対に汚さない
console.error("[sandbox-server] stdio でリクエストを待機しています");
