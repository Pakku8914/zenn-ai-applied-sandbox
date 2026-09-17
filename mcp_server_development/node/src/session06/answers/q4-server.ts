/**
 * 問題4 の解答：stdio エントリーポイント
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createDashboardServerQ4 } from "./q4-create-server.js";

const server = createDashboardServerQ4();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-q4] stdio でリクエストを待機しています");
