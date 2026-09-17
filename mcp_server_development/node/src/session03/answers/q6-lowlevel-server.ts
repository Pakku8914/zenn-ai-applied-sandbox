/**
 * 問題6 の解答：低水準 Server 版の stdio エントリーポイント
 * 接続の書き方は McpServer 版と同一です。違うのはサーバー定義の側だけ。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createLowLevelServerQ6 } from "./q6-lowlevel-create-server.js";

const server = createLowLevelServerQ6();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-lowlevel] stdio でリクエストを待機しています");
