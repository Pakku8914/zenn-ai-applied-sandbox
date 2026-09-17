/**
 * Bad 実装の stdio エントリーポイント（比較実験用）
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createBadDashboardServer } from "./bad-create-server.js";

const server = createBadDashboardServer();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-bad] stdio でリクエストを待機しています");
