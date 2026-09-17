import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createExportServer } from "./q4-create-server.js";

const server = createExportServer();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-q4] stdio でリクエストを待機しています");
