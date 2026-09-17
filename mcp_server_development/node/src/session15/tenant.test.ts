import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  SessionConflictError,
  UnknownTenantError,
  createTenantRegistry,
} from "./tenant.js";

const FIXED_TIME = 1_700_000_000_000;
const PEPPER = "0123456789abcdef";

let acmeRoot = "";
let betaRoot = "";

beforeAll(() => {
  acmeRoot = fs.mkdtempSync(path.join(os.tmpdir(), "acme-"));
  betaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "beta-"));
  fs.writeFileSync(path.join(acmeRoot, "alpha.md"), "# alpha\n\nalpha だけの文書です。\n", "utf8");
  fs.writeFileSync(path.join(betaRoot, "bravo.md"), "# bravo\n\nbravo だけの文書です。\n", "utf8");
});

afterAll(() => {
  fs.rmSync(acmeRoot, { recursive: true, force: true });
  fs.rmSync(betaRoot, { recursive: true, force: true });
});

function registry() {
  return createTenantRegistry({
    tenants: [
      { tenantId: "acme", docsRoot: acmeRoot, capacity: 20, refillPerSecond: 5 },
      { tenantId: "beta", docsRoot: betaRoot, capacity: 20, refillPerSecond: 5 },
    ],
    now: () => FIXED_TIME,
    pepper: PEPPER,
    sink: () => {}, // テストではログを捨てる
    nonce: () => "test000000000000",
  });
}

async function connect(server: McpServer): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "tenant-test", version: "1.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return client;
}

type Structured = { totalMatched?: number };

describe("テナント境界", () => {
  it("自テナントの文書は検索できる", async () => {
    const client = await connect(
      registry().serverFor({ tenantId: "acme", subjectId: "u1", sessionId: "s1" }),
    );
    const result = (await client.callTool({
      name: "search_documents",
      arguments: { query: "alpha" },
    })) as { structuredContent?: Structured };
    expect(result.structuredContent?.totalMatched).toBe(1);
    await client.close();
  });

  it("他テナントの文書は検索に出てこない", async () => {
    const client = await connect(
      registry().serverFor({ tenantId: "acme", subjectId: "u1", sessionId: "s1" }),
    );
    const result = (await client.callTool({
      name: "search_documents",
      arguments: { query: "bravo" },
    })) as { structuredContent?: Structured };
    expect(result.structuredContent?.totalMatched).toBe(0);
    await client.close();
  });

  it("他テナントの文書は URI を知っていても読めない", async () => {
    const client = await connect(
      registry().serverFor({ tenantId: "acme", subjectId: "u1", sessionId: "s1" }),
    );
    await expect(client.readResource({ uri: "docs://bravo.md" })).rejects.toMatchObject({
      code: -32602,
    });
    await client.close();
  });

  it("未登録のテナントは拒否する（文面にテナントIDを出さない）", () => {
    expect(() =>
      registry().serverFor({ tenantId: "unknown", subjectId: "u1", sessionId: "s9" }),
    ).toThrow(UnknownTenantError);
    expect(() =>
      registry().serverFor({ tenantId: "unknown", subjectId: "u1", sessionId: "s9" }),
    ).toThrow(/登録されていません/);
  });
});

describe("セッションの扱い", () => {
  it("同じセッションIDなら同じ実例を返す", () => {
    const store = registry();
    const first = store.serverFor({ tenantId: "acme", subjectId: "u1", sessionId: "s1" });
    const second = store.serverFor({ tenantId: "acme", subjectId: "u1", sessionId: "s1" });
    expect(second).toBe(first);
    expect(store.activeSessions()).toBe(1);
  });

  it("同じセッションIDを別テナントで使い回せない", () => {
    const store = registry();
    store.serverFor({ tenantId: "acme", subjectId: "u1", sessionId: "s1" });
    expect(() =>
      store.serverFor({ tenantId: "beta", subjectId: "u1", sessionId: "s1" }),
    ).toThrow(SessionConflictError);
  });

  it("close() でセッションを捨てられる", () => {
    const store = registry();
    store.serverFor({ tenantId: "acme", subjectId: "u1", sessionId: "s1" });
    store.serverFor({ tenantId: "beta", subjectId: "u2", sessionId: "s2" });
    expect(store.activeSessions()).toBe(2);
    store.close("s1");
    expect(store.activeSessions()).toBe(1);
  });
});

describe("権限最小化", () => {
  it("公開されているのは読み取り専用ツールだけ", async () => {
    const client = await connect(
      registry().serverFor({ tenantId: "acme", subjectId: "u1", sessionId: "s1" }),
    );
    const { tools } = await client.listTools();
    expect(tools.map((tool) => tool.name)).toEqual(["search_documents"]);
    for (const tool of tools) {
      expect(tool.annotations?.readOnlyHint).toBe(true);
      expect(tool.annotations?.destructiveHint).toBe(false);
    }
    await client.close();
  });
});
