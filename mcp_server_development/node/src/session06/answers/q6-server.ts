/**
 * 問題6 の解答：stdio エントリーポイント
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createDashboardServerQ6 } from "./q6-create-server.js";

const server = createDashboardServerQ6();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-q6] stdio でリクエストを待機しています");
