/**
 * 「返した resource_link は全部読める」を契約としてテストする。
 *   docker compose exec node npx vitest run src/review02/q4-contract.test.ts
 *
 * インメモリトランスポートによる契約テストはセッション13 で基礎から扱います。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";

import { createNoticeServer } from "./q4-create-server.js";

type ContentLike = { type: string; uri?: string };

describe("search_notices が返す resource_link", () => {
  it("すべて resources/read で読める", async () => {
    const server = createNoticeServer();
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    const client = new Client({ name: "contract", version: "1.0.0" });
    await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

    const result = (await client.callTool({
      name: "search_notices",
      arguments: { query: "変更" },
    })) as { content: ContentLike[] };
    const uris = result.content
      .filter((block) => block.type === "resource_link")
      .map((block) => block.uri ?? "");

    expect(uris.length).toBe(3);
    for (const uri of uris) {
      const read = await client.readResource({ uri });
      expect(read.contents.length).toBe(1);
    }

    await client.close();
  });
});
