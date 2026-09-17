import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createDashboardServerQ4 } from "./q4-create-server.js";

const server = createDashboardServerQ4();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard] stdio でリクエストを待機しています");
