/**
 * 中間プロジェクト1 の検証用クライアント（インメモリ接続）
 *
 *   docker compose exec node npx tsx src/mid01/verify.ts
 *   docker compose exec node npx tsx src/mid01/verify.ts /tmp/mid01-docs
 *
 * InMemoryTransport でクライアントとサーバーを直結します。子プロセスを起こさないので
 * 起動が速く、出力も安定します。stdio 経路（子プロセスの起動・stdout の純度）の確認は
 * Inspector CLI が担当します ―― 2 つの経路で確認するのが要点です。
 *
 * このスクリプトはクライアント側なので console.log を使ってかまいません
 * （禁止されているのは「サーバープロセスの stdout」だけです）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { resolveDocsRoot } from "./config.js";
import { DOC_TEMPLATE, createDocSearchServer } from "./create-server.js";

type ContentBlock = {
  type: string;
  text?: string;
  uri?: string;
  name?: string;
  mimeType?: string;
  description?: string;
  resource?: { uri: string; mimeType?: string; text?: string };
};

type SearchStructured = {
  query: string;
  directory?: string;
  totalMatched: number;
  returned: number;
  truncated: boolean;
  results: { path: string; uri: string; score: number; snippet: string }[];
};

type ToolResult = {
  content: ContentBlock[];
  structuredContent?: SearchStructured;
  isError?: boolean; [key: string]: unknown };

/** 危険な URI（URI として解釈できるものだけをここに置く。構文レベルの網羅は問題8） */
const DANGEROUS_URIS = [
  "docs://../../etc/passwd",
  "docs:///etc/passwd",
  "docs://..%2f..%2fetc%2fpasswd",
  "docs://%2e%2e%2fsecret.md",
  "docs://guides/../../etc/passwd",
  "docs://onboarding.txt",
  "docs://missing.md",
  "docs://guides",
] as const;

const docsRoot = resolveDocsRoot();

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const server = createDocSearchServer({ docsRoot });
const client = new Client({ name: "mid01-verify", version: "1.0.0" });
await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

function digest(result: SearchStructured | undefined): string {
  return (result?.results ?? []).map((hit) => `${hit.path}(${hit.score})`).join(", ");
}

async function search(args: Record<string, unknown>): Promise<ToolResult> {
  return (await client.callTool({ name: "search_documents", arguments: args })) as ToolResult;
}

function errorCodeOf(error: unknown): number | undefined {
  return (error as { code?: number }).code;
}

const info = client.getServerVersion();
const capabilities = client.getServerCapabilities();
console.log(
  `[1/14] 接続: ${info?.name} v${info?.version}` +
    ` / tools=${capabilities?.tools !== undefined}` +
    ` / resources=${capabilities?.resources !== undefined}` +
    ` / prompts=${capabilities?.prompts !== undefined}` +
    ` / completions=${capabilities?.completions !== undefined}` +
    ` / docsRoot=${docsRoot}`,
);

const { tools } = await client.listTools();
const tool = tools[0];
console.log(
  `[2/14] tools/list: ${tools.length} 本 → ${tool?.name}` +
    ` / readOnlyHint=${tool?.annotations?.readOnlyHint}` +
    ` / destructiveHint=${tool?.annotations?.destructiveHint}` +
    ` / idempotentHint=${tool?.annotations?.idempotentHint}` +
    ` / openWorldHint=${tool?.annotations?.openWorldHint}` +
    ` / outputSchema=${tool?.outputSchema !== undefined}`,
);

const templates = await client.listResourceTemplates();
const templateHead = templates.resourceTemplates[0];
console.log(
  `[3/14] resources/templates/list: ${templates.resourceTemplates.length} 件` +
    ` → ${templateHead?.uriTemplate}（mimeType=${templateHead?.mimeType}）`,
);

const listed = await client.listResources();
console.log(
  `[4/14] resources/list: ${listed.resources.length} 件` +
    ` → ${listed.resources.map((resource) => resource.uri).join(", ")}`,
);

const vpn = await search({ query: "VPN" });
console.log(
  `[5/14] query="VPN": totalMatched=${vpn.structuredContent?.totalMatched}` +
    ` / returned=${vpn.structuredContent?.returned}` +
    ` / truncated=${vpn.structuredContent?.truncated}` +
    ` / 順序=${digest(vpn.structuredContent)}`,
);

const containsBody = vpn.content.some((block) => (block.text ?? "").includes("# VPN 接続手順"));
const firstLink = vpn.content.find((block) => block.type === "resource_link");
console.log(
  `[6/14] content の種別=${vpn.content.map((block) => block.type).join(",")}` +
    ` / 本文を含まない=${!containsBody}` +
    ` / 先頭 link=${firstLink?.uri}` +
    ` / 抜粋=${vpn.structuredContent?.results[0]?.snippet}`,
);

const limited = await search({ query: "VPN", limit: 2 });
console.log(
  `[7/14] limit=2: totalMatched=${limited.structuredContent?.totalMatched}` +
    ` / returned=${limited.structuredContent?.returned}` +
    ` / truncated=${limited.structuredContent?.truncated}`,
);

const faq = await search({ query: "ロック", directory: "faq" });
console.log(
  `[8/14] directory="faq": totalMatched=${faq.structuredContent?.totalMatched}` +
    ` / directory=${faq.structuredContent?.directory}` +
    ` / 順序=${digest(faq.structuredContent)}`,
);

const andQuery = await search({ query: "障害 連絡" });
console.log(
  `[9/14] AND 検索: totalMatched=${andQuery.structuredContent?.totalMatched}` +
    ` / 順序=${digest(andQuery.structuredContent)}`,
);

const none = await search({ query: "ゼロトラスト" });
console.log(
  `[10/14] 0 件: isError=${none.isError === true}` +
    ` / content=${none.content.map((block) => block.type).join(",")}` +
    ` / results=${none.structuredContent?.results.length} 件`,
);

const invalid = await search({ query: "   " });
console.log(
  `[11/14] 不正な検索語: isError=${invalid.isError === true}` +
    ` / message=${invalid.content[0]?.text}`,
);

const read = await client.readResource({ uri: "docs://guides/vpn-setup.md" });
const contents = read.contents as { uri: string; mimeType?: string; text?: string }[];
const head = contents[0];
const body = head?.text ?? "";
console.log(
  `[12/14] resources/read: uri=${head?.uri} / mimeType=${head?.mimeType}` +
    ` / 行数=${body.trimEnd().split("\n").length}` +
    ` / 1行目=${body.split("\n")[0]}`,
);

const completion = await client.complete({
  ref: { type: "ref/resource", uri: DOC_TEMPLATE },
  argument: { name: "path", value: "gui" },
});
console.log(
  `[13/14] 補完（path="gui"）: ${completion.completion.values.join(", ")}` +
    ` / hasMore=${completion.completion.hasMore === true}`,
);

const prompt = await client.getPrompt({ name: "summarize_search", arguments: { query: "VPN" } });
const messages = prompt.messages as { role: string; content: ContentBlock }[];
console.log(
  `[14/14] prompts/get: messages=${messages.length}` +
    ` / 1件目=${messages[0]?.content.type} / 2件目=${messages[1]?.content.type}` +
    `（uri=${messages[1]?.content.resource?.uri}）`,
);

// 異常系：例外になるので try / catch で受ける（ツールの isError と違う点）
const codes: string[] = [];
for (const uri of DANGEROUS_URIS) {
  try {
    await client.readResource({ uri });
    codes.push(`${uri}=読めてしまった`);
  } catch (error) {
    codes.push(`${uri}=${errorCodeOf(error)}`);
  }
}
console.log(`[パス検証] ${codes.join(" / ")}`);

await client.close();
console.log("OK: 中間プロジェクト1 のサーバーは要求仕様どおりに応答しています");
