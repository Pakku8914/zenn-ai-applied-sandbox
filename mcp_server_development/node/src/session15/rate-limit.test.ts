import path from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";

import { createAuditLogger } from "./audit-log.js";
import { createGuardedDocSearchServer } from "./guarded-server.js";
import { createRateLimiter } from "./rate-limit.js";

const DOCS_ROOT = path.resolve("src/session15/docs-tainted");
const PEPPER = "0123456789abcdef";
const FIXED_TIME = 1_700_000_000_000;

describe("トークンバケット", () => {
  it("容量ぶんは許可し、超えた 1 回を拒否する", () => {
    const limiter = createRateLimiter({ capacity: 5, refillPerSecond: 1, now: () => 1_000 });

    const remainings: number[] = [];
    for (let index = 0; index < 5; index += 1) {
      const decision = limiter.tryConsume("acme:user-1");
      expect(decision.allowed).toBe(true);
      if (decision.allowed) {
        remainings.push(decision.remaining);
      }
    }
    expect(remainings).toEqual([4, 3, 2, 1, 0]);

    const denied = limiter.tryConsume("acme:user-1");
    expect(denied.allowed).toBe(false);
    if (!denied.allowed) {
      expect(denied.retryAfterMs).toBe(1_000);
    }
  });

  it("時計を進めると回復する（実時間は 1 ミリ秒も待たない）", () => {
    let clock = 1_000;
    const limiter = createRateLimiter({ capacity: 5, refillPerSecond: 1, now: () => clock });
    for (let index = 0; index < 5; index += 1) {
      limiter.tryConsume("acme:user-1");
    }
    expect(limiter.tryConsume("acme:user-1").allowed).toBe(false);

    clock += 2_500; // 2.5 秒ぶん = 2.5 トークン回復
    const first = limiter.tryConsume("acme:user-1");
    expect(first.allowed).toBe(true);
    if (first.allowed) {
      expect(first.remaining).toBe(1); // 2.5 - 1 = 1.5 → floor で 1
    }
    expect(limiter.tryConsume("acme:user-1").allowed).toBe(true);
    expect(limiter.tryConsume("acme:user-1").allowed).toBe(false);
  });

  it("キーごとに独立している", () => {
    const limiter = createRateLimiter({ capacity: 1, refillPerSecond: 1, now: () => 1_000 });
    expect(limiter.tryConsume("acme:user-1").allowed).toBe(true);
    expect(limiter.tryConsume("acme:user-1").allowed).toBe(false);
    // 別の利用者は影響を受けない
    expect(limiter.tryConsume("acme:user-2").allowed).toBe(true);
    // 別のテナントも独立している
    expect(limiter.tryConsume("beta:user-1").allowed).toBe(true);
    expect(limiter.size()).toBe(3);
  });

  it("maxKeys を超えたら最も古いバケットを捨てる（メモリ枯渇対策）", () => {
    let clock = 1_000;
    const limiter = createRateLimiter({
      capacity: 1,
      refillPerSecond: 1,
      now: () => clock,
      maxKeys: 2,
    });
    limiter.tryConsume("a");
    clock += 10;
    limiter.tryConsume("b");
    clock += 10;
    limiter.tryConsume("c");
    expect(limiter.size()).toBe(2);
  });
});

describe("ガード付きサーバーに配線されている（契約テスト）", () => {
  it("capacity を超えた呼び出しが isError で返り、監査ログに残る", async () => {
    const logLines: string[] = [];
    const audit = createAuditLogger({
      server: "docsearch-guarded",
      tenantId: "acme",
      subjectId: "user-1",
      sessionId: "session-1",
      pepper: PEPPER,
      clock: () => FIXED_TIME,
      sink: (line) => logLines.push(line),
    });
    const server = createGuardedDocSearchServer({
      docsRoot: DOCS_ROOT,
      tenant: { tenantId: "acme", subjectId: "user-1", sessionId: "session-1" },
      audit,
      limiter: createRateLimiter({ capacity: 3, refillPerSecond: 1, now: () => FIXED_TIME }),
      nonce: () => "test000000000000",
      clock: () => FIXED_TIME,
    });

    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    const client = new Client({ name: "rate-limit-test", version: "1.0.0" });
    await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

    const isErrorFlags: boolean[] = [];
    let lastMessage = "";
    for (let index = 0; index < 4; index += 1) {
      const result = (await client.callTool({
        name: "search_documents",
        arguments: { query: "VPN" },
      })) as { isError?: boolean; content: { type: string; text?: string }[] };
      isErrorFlags.push(result.isError === true);
      lastMessage = result.content[0]?.text ?? "";
    }

    // 1〜3 回目が成功していることも確認する（全部失敗でも「4 回目が失敗」は満たされる）
    expect(isErrorFlags).toEqual([false, false, false, true]);
    expect(lastMessage).toContain("上限に達しました");

    const rateLimited = logLines
      .map((line) => JSON.parse(line) as { event: string })
      .filter((record) => record.event === "rate_limited");
    expect(rateLimited).toHaveLength(1);

    await client.close();
  });
});
