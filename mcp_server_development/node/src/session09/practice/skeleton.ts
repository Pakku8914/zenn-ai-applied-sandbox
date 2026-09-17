import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import {
  CreateMessageRequestSchema,
  ElicitRequestSchema,
  ListRootsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const server = new McpServer({ name: "practice", version: "1.0.0" });
// TODO: ツールを登録する

const client = new Client(
  { name: "practice-client", version: "1.0.0" },
  // TODO: 使う機能だけを申告する（申告とハンドラは必ずセット）
  { capabilities: {} },
);
// TODO: 必要なリクエストハンドラを登録する

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

// TODO: 検証する

await client.close();
await server.close();
