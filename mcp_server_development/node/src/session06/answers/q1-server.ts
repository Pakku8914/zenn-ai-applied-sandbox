/**
 * 問題1 の解答：stdio エントリーポイント
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createDashboardServerQ1 } from "./q1-create-server.js";

const server = createDashboardServerQ1();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-q1] stdio でリクエストを待機しています");
