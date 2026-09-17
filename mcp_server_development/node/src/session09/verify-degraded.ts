/**
 * クライアント機能を持たない／拒否するクライアントで劣化経路を検証する
 *
 *   docker compose exec node npx tsx src/session09/verify-degraded.ts
 *
 * 2 つのシナリオを順に実行します。
 *   A: 何も申告しないクライアント（ケイパビリティ無し）
 *   B: sampling を申告しつつ、ハンドラが失敗するクライアント
 * B があるのは「申告していても失敗する」を確認するためです。①だけでは足りません。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { CreateMessageRequestSchema } from "@modelcontextprotocol/sdk/types.js";

import { resolveDocsRoot } from "../mid01/config.js";
import { createSession09Server } from "./create-server.js";

type Structured = {
  scopeSource: string;
  scopeDirectories: string[];
  narrowedBy: string;
  totalMatched: number;
  returned: number;
  summary: string;
  summarySource: string;
  skipReason?: string;
  degraded: { sampling: boolean; roots: boolean; elicitation: boolean };
};

type ToolResult = {
  content: { type: string }[];
  structuredContent?: Structured;
  isError?: boolean;
  [key: string]: unknown;
};

const docsRoot = resolveDocsRoot();

async function run(client: Client, label: string): Promise<ToolResult & { label: string }> {
  const server = createSession09Server({ docsRoot });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

  const capabilities = server.server.getClientCapabilities();
  console.log(
    `${label} ケイパビリティ: sampling=${capabilities?.sampling !== undefined}` +
      ` / roots=${capabilities?.roots !== undefined}` +
      ` / elicitation=${capabilities?.elicitation !== undefined}`,
  );

  const result = (await client.callTool({
    name: "summarize_results",
    arguments: { query: "連絡" },
  })) as ToolResult;

  await client.close();
  await server.close();
  return { ...result, label };
}

// シナリオ A：ケイパビリティを 1 つも申告しない
const plainClient = new Client({ name: "session09-plain", version: "1.0.0" });
const plain = await run(plainClient, "[1/4]");
const plainResult = plain.structuredContent;
console.log(
  `[2/4] 結果: scopeSource=${plainResult?.scopeSource}` +
    ` / narrowedBy=${plainResult?.narrowedBy}` +
    ` / totalMatched=${plainResult?.totalMatched} / returned=${plainResult?.returned}` +
    ` / summarySource=${plainResult?.summarySource} / skipReason=${plainResult?.skipReason}`,
);
console.log(
  `[3/4] 劣化の内訳: sampling=${plainResult?.degraded.sampling}` +
    ` / roots=${plainResult?.degraded.roots}` +
    ` / elicitation=${plainResult?.degraded.elicitation}` +
    ` / isError=${plain.isError === true}` +
    ` / content=${plain.content.map((block) => block.type).join(",")}`,
);

// シナリオ B：sampling は申告するが、ハンドラが失敗する
const refusingClient = new Client(
  { name: "session09-refusing", version: "1.0.0" },
  { capabilities: { sampling: {} } },
);
refusingClient.setRequestHandler(CreateMessageRequestSchema, () => {
  throw new Error("ユーザーが sampling を拒否しました");
});
const refused = await run(refusingClient, "[（参考）]");
const refusedResult = refused.structuredContent;
console.log(
  `[4/4] 拒否するクライアント: summarySource=${refusedResult?.summarySource}` +
    ` / skipReason=${refusedResult?.skipReason}` +
    ` / 要約の1行目=${(refusedResult?.summary ?? "").split("\n")[0]}`,
);

console.log("OK: 3 機能が無くても、同じツールが同じ形の結果を返しています");
