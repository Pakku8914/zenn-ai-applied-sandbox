/**
 * テストの土台（テスト専用のヘルパー）
 *
 * ここに置くのは「書き味を決める道具」だけで、期待値の判断はテスト側に書きます。
 * 道具が判断を持つと、テストを読んでも何を保証しているのか分からなくなります。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { type AuthContext, SCOPE_APPROVE, SCOPE_READ, SCOPE_WRITE } from "./auth/scopes.js";
import { type ScanReport, createWorkflowServer } from "./create-server.js";
import { type Store, createStore } from "./domain/workflow.js";
import { createAuditLogger } from "./observability/audit.js";

export const ALL_SCOPES: readonly string[] = [SCOPE_READ, SCOPE_WRITE, SCOPE_APPROVE];

export function authWith(scopes: readonly string[]): AuthContext {
  return {
    subject: "user-1001",
    clientId: "test-client",
    scopes,
    expiresAt: 4_102_444_800,
    tokenRef: "test0000",
    tenantId: "acme",
  };
}

export type ToolCallResult = {
  content?: Array<{ type: string; text?: string; uri?: string }>;
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
};

export type Harness = {
  client: Client;
  store: Store;
  /** 監査ログの 1 行ずつ */
  lines: string[];
  scans: ScanReport[];
  close(): Promise<void>;
};

export type HarnessOptions = {
  readonly scopes?: readonly string[];
  readonly rateLimit?: { readonly capacity: number; readonly refillPerSecond: number };
  readonly now?: () => number;
};

export async function startHarness(options: HarnessOptions = {}): Promise<Harness> {
  const store = createStore();
  const lines: string[] = [];
  const scans: ScanReport[] = [];
  const audit = createAuditLogger({
    server: "workflow-requests",
    pepper: "test-pepper",
    clock: () => 0,
    sink: (line) => lines.push(line),
    knownSecrets: ["ghp_TESTSECRETVALUE0001"],
  });
  const context = authWith(options.scopes ?? ALL_SCOPES);
  const server = createWorkflowServer({
    store,
    audit,
    auth: () => context,
    onScan: (report) => scans.push(report),
    ...(options.rateLimit === undefined ? {} : { rateLimit: options.rateLimit }),
    ...(options.now === undefined ? {} : { now: options.now }),
  });

  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "final-test", version: "1.0.0" });
  // 両側の connect をまとめて待つ。片方だけ待つとハングすることがある
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

  return {
    client,
    store,
    lines,
    scans,
    close: async () => {
      await client.close();
      await server.close();
    },
  };
}

export async function callTool(
  client: Client,
  name: string,
  args: Record<string, unknown> = {},
): Promise<ToolCallResult> {
  return (await client.callTool({ name, arguments: args })) as unknown as ToolCallResult;
}

export function textOf(result: ToolCallResult): string {
  return (result.content ?? []).map((block) => block.text ?? "").join("\n");
}

/** ドライランの出力から previewToken を拾う */
export function pickToken(message: string): string {
  return /previewToken: (\S+)/.exec(message)?.[1] ?? "";
}
