  import http from "node:http";

  import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

  import { createDocSearchLiteServer } from "./create-server-lite.js";

  let counter = 0;
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: () => `session-${(counter += 1)}`,
  });
  const server = createDocSearchLiteServer();
  await server.connect(transport);

  const httpServer = http.createServer(async (req, res) => {
    console.log(`${req.method} ${req.url}`);
    await transport.handleRequest(req, res);
  });

  httpServer.listen(3939, "0.0.0.0");
  console.log("listening on 0.0.0.0:3939");
