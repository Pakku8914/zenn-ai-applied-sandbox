import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { createRoomStore } from "./rooms.js";

const store = createRoomStore();
const server = new McpServer({ name: "rooms-practice", version: "1.0.0" });
// TODO: ツールを登録する

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "rooms-practice-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

// TODO: 検証する

await client.close();
await server.close();
