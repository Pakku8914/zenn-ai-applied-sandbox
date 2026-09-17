/**
 * 問題5 の解答：stdio エントリーポイント
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createDashboardServerQ5 } from "./q5-create-server.js";

const server = createDashboardServerQ5();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-q5] stdio でリクエストを待機しています");
