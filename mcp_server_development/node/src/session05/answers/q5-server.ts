import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createReviewedServer } from "./q5-create-server.js";

const server = createReviewedServer();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-q5] stdio でリクエストを待機しています");
