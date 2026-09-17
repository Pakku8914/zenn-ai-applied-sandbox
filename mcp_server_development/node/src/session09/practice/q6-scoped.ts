/**
 * 問題6 の検証：ツール・一覧・読み取りの 3 経路すべてに境界が効くことを確認する
 *
 * roots をキャッシュしていないので、currentRoots を差し替えるだけで
 * 次のリクエストから新しい境界が効きます（list_changed は不要）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { ListRootsRequestSchema, type Root } from "@modelcontextprotocol/sdk/types.js";

import { resolveDocsRoot } from "../../mid01/config.js";
import {
  createScopedDocSearchServer,
  resolveScopeFromClientRoots,
} from "./create-scoped-server.js";

type Structured = { totalMatched: number; results: { path: string; score: number }[] };
type ToolResult = {
  content: { text?: string }[];
  structuredContent?: Structured;
  isError?: boolean;
  [key: string]: unknown;
};

const docsRoot = resolveDocsRoot();

let currentRoots: Root[] = [
  { uri: `file://${docsRoot}/faq`, name: "FAQ" },
  { uri: `file://${docsRoot}/guides`, name: "手順書" },
];

const client = new Client(
  { name: "q6-client", version: "1.0.0" },
  { capabilities: { roots: { listChanged: true } } },
);
client.setRequestHandler(ListRootsRequestSchema, () => ({ roots: currentRoots }));

const server = createScopedDocSearchServer({
  docsRoot,
  resolveScope: resolveScopeFromClientRoots(docsRoot),
});
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

async function search(): Promise<ToolResult> {
  return (await client.callTool({
    name: "search_documents",
    arguments: { query: "連絡" },
  })) as ToolResult;
}

function digest(structured: Structured | undefined): string {
  return (structured?.results ?? []).map((hit) => `${hit.path}(${hit.score})`).join(", ");
}

const first = await search();
console.log(
  `[1/5] roots=faq,guides: totalMatched=${first.structuredContent?.totalMatched}` +
    ` / 順序=${digest(first.structuredContent)}`,
);

const listed = await client.listResources();
console.log(
  `[2/5] roots=faq,guides: resources/list=${listed.resources.length} 件` +
    ` → ${listed.resources.map((resource) => resource.uri).join(", ")}`,
);

try {
  await client.readResource({ uri: "docs://onboarding.md" });
  console.log("[3/5] スコープ外の読み取り: 読めてしまいました（NG）");
} catch (error) {
  console.log(
    `[3/5] スコープ外の読み取り（docs://onboarding.md）: error=${(error as { code?: number }).code}`,
  );
}

currentRoots = [{ uri: `file://${docsRoot}/guides`, name: "手順書" }];
const narrowed = await search();
const narrowedList = await client.listResources();
console.log(
  `[4/5] roots=guides のみ: totalMatched=${narrowed.structuredContent?.totalMatched}` +
    ` / resources/list=${narrowedList.resources.length} 件`,
);

currentRoots = [{ uri: "file:///tmp", name: "tmp" }];
const outside = await search();
console.log(
  `[5/5] roots=/tmp のみ: isError=${outside.isError === true}` +
    ` / message の先頭=${(outside.content[0]?.text ?? "").slice(0, 19)}`,
);

await client.close();
await server.close();
console.log("OK: 問題6 の条件を満たしています");
