/**
 * 比較用：低水準 Server 版の stdio エントリーポイント
 *
 * 接続の書き方は McpServer とまったく同じです（connect の引数にトランスポートを渡す）。
 * 違いはサーバー定義の側だけ、という点を確認してください。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createLowLevelServer } from "./lowlevel-create-server.js";

const server = createLowLevelServer();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-lowlevel] stdio でリクエストを待機しています");
