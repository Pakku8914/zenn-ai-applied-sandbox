import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";

import { createSearchServer } from "./q4-budget.js";

describe("search_reservations の上限付き返却", () => {
  it("上限で切ったら omitted と nextCursor を返す", async () => {
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    const client = new Client({ name: "test", version: "1.0.0" });
    await createSearchServer().connect(serverTransport);
    await client.connect(clientTransport);

    const result = await client.callTool({ name: "search_reservations", arguments: { limit: 50 } });
    const output = result.structuredContent as { omitted?: number; hasMore: boolean; nextCursor?: string };

    expect(output.omitted).toBeGreaterThan(0);
    expect(output.hasMore).toBe(true);
    expect(output.nextCursor).toBeTypeOf("string");
    await client.close();
  });
});
