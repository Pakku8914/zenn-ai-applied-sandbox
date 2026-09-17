import path from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";

import { createAuditLogger } from "./audit-log.js";
import { createGuardedDocSearchServer } from "./guarded-server.js";
import { createRateLimiter } from "./rate-limit.js";

/** 架空のトークン。本物を書かない */
const KNOWN_TOKEN = "ghp_0123456789abcdefghijABCDEF";
/** 既知の秘密として登録していないトークン（パターンで拾えるかの確認用） */
const UNKNOWN_TOKEN = "sk-abcdefghijklmnopqrstuvwx";
const PEPPER = "0123456789abcdef";
const OTHER_PEPPER = "fedcba9876543210";
const FIXED_TIME = 1_700_000_000_000;
const DOCS_ROOT = path.resolve("src/session15/docs-tainted");

function loggerWithSink(lines: string[], pepper = PEPPER) {
  return createAuditLogger({
    server: "docsearch-guarded",
    tenantId: "acme",
    subjectId: "user-42@example.com",
    sessionId: "session-abcdef",
    pepper,
    clock: () => FIXED_TIME,
    sink: (line) => lines.push(line),
    knownSecrets: [KNOWN_TOKEN],
  });
}

describe("監査ログ ―― 秘密情報", () => {
  it("既知の秘密値がログ行に現れない", () => {
    const lines: string[] = [];
    loggerWithSink(lines).write({
      event: "internal_error",
      target: "upstream",
      outcome: "error",
      params: { note: `Authorization: Bearer ${KNOWN_TOKEN}` },
    });
    const line = lines[0] ?? "";
    expect(line).not.toContain(KNOWN_TOKEN);
    expect(line).toContain("[REDACTED]");
  });

  it("既知でなくてもトークンらしい文字列は落とす", () => {
    const lines: string[] = [];
    loggerWithSink(lines).write({
      event: "internal_error",
      target: "upstream",
      outcome: "error",
      params: { note: `key=${UNKNOWN_TOKEN}` },
    });
    expect(lines[0] ?? "").not.toContain(UNKNOWN_TOKEN);
  });

  it("値に改行を混ぜてもログ行を増やせない（ログインジェクション）", () => {
    const lines: string[] = [];
    loggerWithSink(lines).write({
      event: "resource_read",
      target: 'docs://a\n{"event":"fake","outcome":"ok"}',
      outcome: "rejected",
      reason: "not_found",
    });
    expect(lines).toHaveLength(1);
    const line = lines[0] ?? "";
    expect(line.includes("\n")).toBe(false);
    const record = JSON.parse(line) as { target: string };
    expect(record.target.includes("\n")).toBe(false);
    expect(record.target).toContain('docs://a {"event":"fake"');
  });

  it("参照値は 16 桁の 16 進数で、同じ入力なら同じ値になる", () => {
    const logger = loggerWithSink([]);
    const first = logger.hash("VPN");
    expect(first).toMatch(/^[0-9a-f]{16}$/);
    expect(logger.hash("VPN")).toBe(first);
    expect(logger.hash("vpn")).not.toBe(first);
  });

  it("ペッパーが違えば同じ入力でも違う参照値になる", () => {
    const a = loggerWithSink([], PEPPER).hash("VPN");
    const b = loggerWithSink([], OTHER_PEPPER).hash("VPN");
    expect(a).not.toBe(b);
  });

  it("既定の出力先は stdout ではない（stdio の電文を壊さない）", () => {
    const stderrChunks: string[] = [];
    const stdoutChunks: string[] = [];
    const originalStderr = process.stderr.write;
    const originalStdout = process.stdout.write;
    process.stderr.write = ((chunk: unknown) => {
      stderrChunks.push(String(chunk));
      return true;
    }) as typeof process.stderr.write;
    process.stdout.write = ((chunk: unknown) => {
      stdoutChunks.push(String(chunk));
      return true;
    }) as typeof process.stdout.write;
    try {
      createAuditLogger({
        server: "docsearch-guarded",
        tenantId: "acme",
        subjectId: "user-1",
        sessionId: "session-1",
        pepper: PEPPER,
        clock: () => FIXED_TIME,
      }).write({ event: "tool_call", target: "search_documents", outcome: "ok" });
    } finally {
      // 戻し忘れると後続テストの出力が消える
      process.stderr.write = originalStderr;
      process.stdout.write = originalStdout;
    }
    expect(stderrChunks.join("")).toContain('"event":"tool_call"');
    expect(stdoutChunks.join("")).not.toContain('"event":"tool_call"');
  });
});

describe("監査ログ ―― 生値を渡していないこと（サーバー経由で確認）", () => {
  it("検索語・ディレクトリ・内部パスがログに現れない", async () => {
    const logLines: string[] = [];
    const secretQuery = "機密案件コードネームさくら";
    const audit = createAuditLogger({
      server: "docsearch-guarded",
      tenantId: "acme",
      subjectId: "user-42@example.com",
      sessionId: "session-abcdef",
      pepper: PEPPER,
      clock: () => FIXED_TIME,
      sink: (line) => logLines.push(line),
    });
    const server = createGuardedDocSearchServer({
      docsRoot: DOCS_ROOT,
      tenant: { tenantId: "acme", subjectId: "user-42@example.com", sessionId: "session-abcdef" },
      audit,
      limiter: createRateLimiter({ capacity: 50, refillPerSecond: 10, now: () => FIXED_TIME }),
      nonce: () => "test000000000000",
      clock: () => FIXED_TIME,
    });

    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    const client = new Client({ name: "audit-log-test", version: "1.0.0" });
    await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

    await client.callTool({ name: "search_documents", arguments: { query: secretQuery } });
    // 拒否される読み取り。パスの生値がログに載らないことを確認するために使う
    await expect(
      client.readResource({ uri: "docs://secret-plan.txt" }),
    ).rejects.toMatchObject({ code: -32602 });

    const joined = logLines.join("\n");
    expect(joined).not.toContain(secretQuery); // 検索語の生値
    expect(joined).not.toContain("secret-plan"); // 入力されたパスの生値
    expect(joined).not.toContain(DOCS_ROOT); // サーバー内部の絶対パス
    expect(joined).not.toContain("user-42@example.com"); // 利用者の生の識別子

    const records = logLines.map((line) => JSON.parse(line) as Record<string, unknown>);
    const toolCall = records.find((record) => record.event === "tool_call");
    expect(toolCall).toBeDefined();
    expect(Object.keys(toolCall ?? {})).toContain("subject");
    expect(Object.keys(toolCall ?? {})).toContain("sessionRef");
    const params = (toolCall?.params ?? {}) as Record<string, unknown>;
    expect(params.queryLength).toBe(secretQuery.length);
    expect(params.queryRef).toMatch(/^[0-9a-f]{16}$/);

    // 拒否理由は機械可読な語彙だけが載る（入力値も内部パスも載らない）
    const rejected = records.find((record) => record.outcome === "rejected");
    expect(rejected?.reason).toBe("not_markdown");

    await client.close();
  });
});
