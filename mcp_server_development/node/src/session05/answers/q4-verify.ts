/**
 * 問題4 の解答：動作確認クライアント
 *
 *   docker compose exec node npx tsx src/session05/answers/q4-verify.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

type ToolResult = {
  isError?: boolean;
  content: Array<{ type: string; resource?: { text?: string } }>;
  structuredContent?: Record<string, unknown>;
  [key: string]: unknown;
};

function asResult(result: unknown): ToolResult {
  return result as ToolResult;
}

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/session05/answers/q4-server.ts"],
});
const client = new Client({ name: "q4-verify", version: "1.0.0" });
await client.connect(transport);

const range = { from: "2026-07-27", to: "2026-08-07" };

const csv = asResult(await client.callTool({ name: "export_report", arguments: range }));
const s1 = csv.structuredContent ?? {};
console.log(
  `[1/3] format=${s1["format"]} / delivery=${s1["delivery"]} / mimeType=${s1["mimeType"]} / uri=${s1["uri"]}`,
);

const json = asResult(
  await client.callTool({
    name: "export_report",
    arguments: { ...range, format: "json", inline: true },
  }),
);
const s2 = json.structuredContent ?? {};
const embedded = json.content.find((block) => block.type === "resource");
console.log(
  `[2/3] format=${s2["format"]} / delivery=${s2["delivery"]} / 種別=${json.content
    .map((block) => block.type)
    .join(",")} / 本文の先頭 40 文字=${embedded?.resource?.text?.slice(0, 40)}`,
);

let third = "エラーになりませんでした（列挙が効いていません）";
try {
  await client.callTool({ name: "export_report", arguments: { ...range, format: "xml" } });
} catch (error) {
  third = `JSON-RPC エラー code=${(error as { code?: number }).code}`;
}
console.log(`[3/3] format=xml は ${third}`);

await client.close();
