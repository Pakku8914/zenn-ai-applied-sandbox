import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createAuditableBadServer } from "./q7-bad-create-server.js";

const server = createAuditableBadServer();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-bad-auditable] stdio でリクエストを待機しています");
