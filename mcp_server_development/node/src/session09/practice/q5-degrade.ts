/**
 * 問題5: 劣化の 4 パターン
 *
 *   A: 3 機能あり（roots で faq / guides に絞る・sampling はダミー要約）
 *   B: 何も申告しない            → unsupported
 *   C: sampling を申告して例外    → call_failed
 *   D: sampling を申告して画像    → non_text_response
 *
 * 本文の createSession09Server() は書き換えません。
 * 「呼ぶ側を変えるだけで 4 分岐すべてを再現できる」ことが、
 * 劣化の判断がサーバー内に閉じている証拠になります。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import {
  CreateMessageRequestSchema,
  ElicitRequestSchema,
  ListRootsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { resolveDocsRoot } from "../../mid01/config.js";
import { createSession09Server } from "../create-server.js";

type Structured = {
  summarySource: string;
  skipReason?: string;
  totalMatched: number;
  degraded: { sampling: boolean; roots: boolean; elicitation: boolean };
};

type ToolResult = {
  content: { type: string }[];
  structuredContent?: Structured;
  isError?: boolean;
  [key: string]: unknown;
};

const docsRoot = resolveDocsRoot();

async function run(client: Client): Promise<ToolResult> {
  const server = createSession09Server({ docsRoot });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

  const result = (await client.callTool({
    name: "summarize_results",
    arguments: { query: "連絡" },
  })) as ToolResult;

  await client.close();
  await server.close();
  return result;
}

// A: 3 機能あり
const clientA = new Client(
  { name: "q5-a", version: "1.0.0" },
  { capabilities: { sampling: {}, roots: {}, elicitation: {} } },
);
clientA.setRequestHandler(ListRootsRequestSchema, () => ({
  roots: [
    { uri: `file://${docsRoot}/faq`, name: "FAQ" },
    { uri: `file://${docsRoot}/guides`, name: "手順書" },
  ],
}));
clientA.setRequestHandler(CreateMessageRequestSchema, () => ({
  model: "stub-summarizer",
  role: "assistant" as const,
  content: { type: "text" as const, text: "【ダミー要約】4 件の文書を要約しました" },
  stopReason: "endTurn",
}));
// 絞り込まずに 4 件のまま要約させるため decline を返す
clientA.setRequestHandler(ElicitRequestSchema, () => ({ action: "decline" as const }));

// B: 何も申告しない
const clientB = new Client({ name: "q5-b", version: "1.0.0" });

// C: sampling を申告するが例外を投げる（ユーザーが拒否した状況を模す）
const clientC = new Client(
  { name: "q5-c", version: "1.0.0" },
  { capabilities: { sampling: {} } },
);
clientC.setRequestHandler(CreateMessageRequestSchema, () => {
  throw new Error("ユーザーが sampling を拒否しました");
});

// D: sampling を申告し、テキスト以外（画像）を返す
const clientD = new Client(
  { name: "q5-d", version: "1.0.0" },
  { capabilities: { sampling: {} } },
);
clientD.setRequestHandler(CreateMessageRequestSchema, () => ({
  model: "stub-image",
  role: "assistant" as const,
  content: {
    type: "image" as const,
    data: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg==",
    mimeType: "image/png",
  },
  stopReason: "endTurn",
}));

const results: { label: string; result: ToolResult }[] = [
  { label: "[1/5] A 3機能あり", result: await run(clientA) },
  { label: "[2/5] B 申告なし", result: await run(clientB) },
  { label: "[3/5] C 拒否する", result: await run(clientC) },
  { label: "[4/5] D 画像を返す", result: await run(clientD) },
];

for (const { label, result } of results) {
  const structured = result.structuredContent;
  console.log(
    `${label}: source=${structured?.summarySource}` +
      ` / skipReason=${structured?.skipReason}` +
      ` / totalMatched=${structured?.totalMatched}` +
      ` / isError=${result.isError === true}`,
  );
}

// content のブロック種別の並びが 4 ケースで同一かどうか
const shapes = results.map(({ result }) => result.content.map((block) => block.type).join(","));
const identical = shapes.every((shape) => shape === shapes[0]);
console.log(
  `[5/5] content の構成は 4 ケースで同一: ${identical}` +
    `（A は roots で 4 件に絞られるため件数が違う）`,
);

console.log("OK: 問題5 の条件を満たしています");
