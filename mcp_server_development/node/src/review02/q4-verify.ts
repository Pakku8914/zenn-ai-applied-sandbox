/**
 * 問題4 の確認用クライアント
 *
 *   docker compose exec node npx tsx src/review02/q4-verify.ts
 *
 * このスクリプトはクライアント側なので console.log を使ってかまいません
 * （禁止されているのは「サーバープロセスの stdout」だけです）。
 *
 * [6/8] が本問の核心です。「ツールが返した参照が、本当に読めるか」を機械的に確かめます。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

type ContentLike = { type: string; text?: string; uri?: string; name?: string; mimeType?: string };
type Hit = { slug: string; matchedIn: string; uri: string };
type ToolResult = {
  isError?: boolean;
  content: ContentLike[];
  structuredContent?: { totalMatches?: number; returned?: number; hits?: Hit[]; [key: string]: unknown };
};
type ContentsLike = { uri: string; mimeType?: string; text?: string };

/** SDK の戻り値を読みやすい形に寄せるだけのヘルパー（検証はサーバーと SDK が済ませている） */
function asResult(result: unknown): ToolResult {
  return result as ToolResult;
}

function firstLine(text: string): string {
  return text.split("\n")[0] ?? "";
}

function errorCodeOf(error: unknown): number | undefined {
  return (error as { code?: number }).code;
}

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/review02/q4-server.ts"],
});
const client = new Client({ name: "review02-q4-verify", version: "1.0.0" });
await client.connect(transport);

const info = client.getServerVersion();
const capabilities = client.getServerCapabilities();
console.log(
  `[1/8] 接続: ${info?.name} v${info?.version}` +
    ` / tools=${capabilities?.tools !== undefined}` +
    ` / resources=${capabilities?.resources !== undefined}` +
    ` / completions=${capabilities?.completions !== undefined}`,
);

const tools = await client.listTools();
const search = tools.tools.find((tool) => tool.name === "search_notices");
console.log(
  `[2/8] search_notices: title=${search?.title}` +
    ` / readOnlyHint=${search?.annotations?.readOnlyHint === true}` +
    ` / openWorldHint=${search?.annotations?.openWorldHint === true}` +
    ` / outputSchema=${search?.outputSchema === undefined ? "なし" : "あり"}`,
);

const listed = await client.listResources();
const templates = await client.listResourceTemplates();
console.log(
  `[3/8] resources/list=${listed.resources.length} 件` +
    ` / resources/templates/list=${templates.resourceTemplates.length} 件` +
    ` → ${templates.resourceTemplates.map((template) => template.uriTemplate).join(", ")}`,
);

const network = asResult(
  await client.callTool({ name: "search_notices", arguments: { query: "ネットワーク" } }),
);
console.log(
  `[4/8] query="ネットワーク": totalMatches=${network.structuredContent?.totalMatches}` +
    ` / returned=${network.structuredContent?.returned}` +
    ` / 種別=${network.content.map((block) => block.type).join(",")}`,
);

const hits = network.structuredContent?.hits ?? [];
console.log(
  `[5/8] hits: ${hits.map((hit) => `${hit.slug}(${hit.matchedIn})`).join(", ")}` +
    ` / uri=${hits.map((hit) => hit.uri).join(", ")}`,
);

// 返した resource_link が本当に読めるかを 1 件ずつ確かめる（これが resource_link の約束）
const uris = network.content
  .filter((block) => block.type === "resource_link")
  .map((block) => block.uri ?? "");
let readOk = 0;
let firstMimeType = "";
let firstHeading = "";
for (const uri of uris) {
  const read = await client.readResource({ uri });
  const [head] = read.contents as ContentsLike[];
  if (head === undefined) {
    continue;
  }
  readOk += 1;
  if (readOk === 1) {
    firstMimeType = head.mimeType ?? "";
    firstHeading = firstLine(head.text ?? "");
  }
}
console.log(
  `[6/8] リンクを全部読む: ${readOk}/${uris.length} 件成功` +
    ` / mimeType=${firstMimeType} / 1行目=${firstHeading}`,
);

const changed = asResult(
  await client.callTool({ name: "search_notices", arguments: { query: "変更" } }),
);
const limited = asResult(
  await client.callTool({ name: "search_notices", arguments: { query: "変更", limit: 2 } }),
);
const facility = asResult(
  await client.callTool({
    name: "search_notices",
    arguments: { query: "変更", category: "facility" },
  }),
);
const facilitySlugs = (facility.structuredContent?.hits ?? []).map((hit) => hit.slug).join(", ");
console.log(
  `[7/8] query="変更": totalMatches=${changed.structuredContent?.totalMatches}` +
    ` / limit=2 で returned=${limited.structuredContent?.returned}` +
    ` / category=facility で returned=${facility.structuredContent?.returned}（${facilitySlugs}）`,
);

const none = asResult(
  await client.callTool({ name: "search_notices", arguments: { query: "リモートワーク" } }),
);
const codes: string[] = [];
for (const [label, uri] of [
  ["未知スラッグ", "notice://unknown-notice"],
  ["traversal", "notice://..%2f..%2f..%2fetc%2fpasswd"],
] as const) {
  try {
    await client.readResource({ uri });
    codes.push(`${label}=読めてしまった`);
  } catch (error) {
    codes.push(`${label}=${errorCodeOf(error)}`);
  }
}
console.log(
  `[8/8] query="リモートワーク": totalMatches=${none.structuredContent?.totalMatches}` +
    ` / isError=${none.isError === true}` +
    ` / 種別=${none.content.map((block) => block.type).join(",")}` +
    ` ／ ${codes.join(" / ")}`,
);

await client.close();
console.log("OK: 検索結果の resource_link はすべて resources/read で読めます");
