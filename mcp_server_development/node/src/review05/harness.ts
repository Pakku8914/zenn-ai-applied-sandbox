/**
 * 契約テストの道具（セッション13 の harness.ts / schema-digest.ts の縮小版）
 *
 * 道具は判断をしません。期待値の判断はテスト側に書きます。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

export type ToolResult = {
  readonly content: readonly { readonly type: string; readonly text?: string }[];
  readonly structuredContent?: Record<string, unknown>;
  readonly isError?: boolean;
};

/** 両側の connect を Promise.all でまとめて待つ（片方だけ待つとハングすることがある） */
export async function connectInMemory(server: McpServer, clientName = "review05"): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: clientName, version: "1.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return client;
}

export async function callTool(
  client: Client,
  name: string,
  args: Record<string, unknown> = {},
): Promise<ToolResult> {
  return (await client.callTool({ name, arguments: args })) as unknown as ToolResult;
}

export function toolText(result: ToolResult): string {
  return result.content.map((block) => block.text ?? "").join("\n");
}

/** 「ツール実行の失敗」を受け取る。isError の確認をここに寄せる */
export function failureText(result: ToolResult): string {
  if (result.isError !== true) {
    throw new Error(`失敗するはずの呼び出しが成功しました: ${toolText(result).slice(0, 120)}`);
  }
  return toolText(result);
}

// ── スキーマダイジェスト（セッション13） ──────────────────────────────────
export type ArgumentDigest = { name: string; required: boolean; hasDescription: boolean };

export type ToolDigest = {
  name: string;
  title: string | null;
  annotations: {
    readOnlyHint: boolean | null;
    destructiveHint: boolean | null;
    idempotentHint: boolean | null;
    openWorldHint: boolean | null;
  };
  args: ArgumentDigest[];
  hasOutputSchema: boolean;
};

export function compareStrings(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function asBooleanOrNull(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

export function digestTools(tools: readonly unknown[]): ToolDigest[] {
  return tools
    .map((tool) => {
      const record = asRecord(tool);
      const inputSchema = asRecord(record["inputSchema"]);
      const properties = asRecord(inputSchema["properties"]);
      const required = new Set(asStringArray(inputSchema["required"]));
      const annotations = asRecord(record["annotations"]);
      return {
        name: typeof record["name"] === "string" ? record["name"] : "(unknown)",
        title: typeof record["title"] === "string" ? record["title"] : null,
        annotations: {
          readOnlyHint: asBooleanOrNull(annotations["readOnlyHint"]),
          destructiveHint: asBooleanOrNull(annotations["destructiveHint"]),
          idempotentHint: asBooleanOrNull(annotations["idempotentHint"]),
          openWorldHint: asBooleanOrNull(annotations["openWorldHint"]),
        },
        args: Object.keys(properties)
          .sort(compareStrings)
          .map((name) => ({
            name,
            required: required.has(name),
            // 文面そのものは比較しない（推敲でテストが落ちないように）
            hasDescription: typeof asRecord(properties[name])["description"] === "string",
          })),
        hasOutputSchema: record["outputSchema"] !== undefined,
      };
    })
    .sort((left, right) => compareStrings(left.name, right.name));
}
