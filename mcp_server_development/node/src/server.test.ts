/**
 * MCP サーバーのテスト例（TypeScript / インメモリトランスポート）
 *
 * 子プロセスを起動せず、クライアントとサーバーをメモリ上のパイプで直結して検証します。
 * 起動コストがゼロなので、CI で何百回でも回せます。
 *
 * 実行： docker compose exec node npm test
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";

import { createServer } from "./create-server.js";

async function connect(): Promise<Client> {
  const [clientTransport, serverTransport] =
    InMemoryTransport.createLinkedPair();
  const server = createServer();
  await server.connect(serverTransport);

  const client = new Client({ name: "test-client", version: "1.0.0" });
  await client.connect(clientTransport);
  return client;
}

describe("sandbox-server", () => {
  it("tools/list で add ツールを公開している", async () => {
    const client = await connect();
    const { tools } = await client.listTools();

    expect(tools.map((t) => t.name)).toContain("add");
    await client.close();
  });

  it("tools/call で加算結果を返す", async () => {
    const client = await connect();
    const result = await client.callTool({
      name: "add",
      arguments: { a: 2, b: 3 },
    });

    const content = result.content as Array<{ type: string; text?: string }>;
    expect(content[0]?.text).toBe("2 + 3 = 5");
    await client.close();
  });
});
