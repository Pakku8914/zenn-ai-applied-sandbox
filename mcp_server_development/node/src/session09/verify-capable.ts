/**
 * 3 機能すべてに対応したクライアントで検証する（インメモリ接続）
 *
 *   docker compose exec node npx tsx src/session09/verify-capable.ts
 *
 * 実 LLM は使いません。sampling には「決まった文字列を返すハンドラ」を登録します。
 * 出力を決定的にするためです（同じ入力なら同じ出力 ―― 中間プロジェクト1 と同じ方針）。
 *
 * これはクライアント側のスクリプトなので console.log を使ってかまいません。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import {
  CreateMessageRequestSchema,
  ElicitRequestSchema,
  ListRootsRequestSchema,
  type Root,
} from "@modelcontextprotocol/sdk/types.js";

import { resolveDocsRoot } from "../mid01/config.js";
import { createSession09Server } from "./create-server.js";

type Structured = {
  query: string;
  mode: string;
  scopeSource: string;
  scopeDirectories: string[];
  narrowedBy: string;
  narrowedTo?: string;
  totalMatched: number;
  returned: number;
  summary: string;
  summarySource: string;
  model?: string;
  skipReason?: string;
  degraded: { sampling: boolean; roots: boolean; elicitation: boolean };
  results: { path: string; score: number }[];
};

type ToolResult = {
  content: { type: string; text?: string }[];
  structuredContent?: Structured;
  isError?: boolean;
  [key: string]: unknown;
};

const docsRoot = resolveDocsRoot();

/** クライアントが今どこを見せているか。あとで差し替えて list_changed を送る */
let currentRoots: Root[] = [
  { uri: `file://${docsRoot}/faq`, name: "FAQ" },
  { uri: `file://${docsRoot}/guides`, name: "手順書" },
];
let samplingCalls = 0;
let elicitationCalls = 0;
let lastCandidates: string[] = [];

const client = new Client(
  { name: "session09-capable", version: "1.0.0" },
  // ケイパビリティを申告しないとハンドラを登録できない（SDK が防いでくれる）
  { capabilities: { sampling: {}, roots: { listChanged: true }, elicitation: {} } },
);

client.setRequestHandler(ListRootsRequestSchema, () => ({ roots: currentRoots }));

client.setRequestHandler(CreateMessageRequestSchema, (request) => {
  samplingCalls += 1;
  const preference = request.params.modelPreferences;
  // sampling のメッセージの content は「1 ブロック」と「ブロックの配列」の
  // どちらも取りうるので、配列に正規化してから型で絞り込みます
  const promptText = request.params.messages
    .flatMap((message) => (Array.isArray(message.content) ? message.content : [message.content]))
    .map((block) => (block.type === "text" ? block.text : ""))
    .join("\n");
  const documents = (promptText.match(/<document /g) ?? []).length;
  return {
    // ホストが実際に選んだモデル名を返す欄。検証ではダミーの名前にする
    model: "stub-summarizer",
    role: "assistant" as const,
    content: {
      type: "text" as const,
      text:
        `【ダミー要約】${documents} 件の文書を要約しました` +
        `（cost=${preference?.costPriority} / speed=${preference?.speedPriority}` +
        ` / intelligence=${preference?.intelligencePriority}）`,
    },
    stopReason: "endTurn",
  };
});

client.setRequestHandler(ElicitRequestSchema, (request) => {
  elicitationCalls += 1;
  // elicitation の params は「スキーマを渡す形」と「URL を渡す形」のユニオンなので、
  // 使う側で扱う形に絞り込んでから読みます
  const params = request.params as {
    requestedSchema?: { properties?: Record<string, { enum?: string[] }> };
  };
  const property = params.requestedSchema?.properties?.["directory"];
  lastCandidates = property?.enum !== undefined ? [...property.enum] : [];
  // 実際のホストはここでユーザーに尋ねる。検証では固定の回答を返す
  return { action: "accept" as const, content: { directory: "faq" } };
});

const server = createSession09Server({ docsRoot });
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

async function summarize(args: Record<string, unknown>): Promise<ToolResult> {
  return (await client.callTool({ name: "summarize_results", arguments: args })) as ToolResult;
}

function digest(structured: Structured | undefined): string {
  return (structured?.results ?? []).map((hit) => `${hit.path}(${hit.score})`).join(", ");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const capabilities = server.server.getClientCapabilities();
console.log(
  `[1/10] ケイパビリティ: sampling=${capabilities?.sampling !== undefined}` +
    ` / roots=${capabilities?.roots !== undefined}` +
    ` / elicitation=${capabilities?.elicitation !== undefined}`,
);

const { tools } = await client.listTools();
const searchTool = tools.find((tool) => tool.name === "search_documents");
const summarizeTool = tools.find((tool) => tool.name === "summarize_results");
console.log(
  `[2/10] tools/list: ${tools.map((tool) => tool.name).join(", ")}` +
    ` / search: idempotent=${searchTool?.annotations?.idempotentHint}` +
    ` openWorld=${searchTool?.annotations?.openWorldHint}` +
    ` / summarize: idempotent=${summarizeTool?.annotations?.idempotentHint}` +
    ` openWorld=${summarizeTool?.annotations?.openWorldHint}`,
);

const first = await summarize({ query: "連絡" });
const firstResult = first.structuredContent;
console.log(
  `[3/10] roots: 申告=${currentRoots.length} 件 → scopeSource=${firstResult?.scopeSource}` +
    ` / scopeDirectories=${firstResult?.scopeDirectories.join(", ")}`,
);
console.log(
  `[4/10] elicitation: 呼び出し=${elicitationCalls} 回 / 候補=${lastCandidates.join(", ")}` +
    ` / narrowedBy=${firstResult?.narrowedBy} / narrowedTo=${firstResult?.narrowedTo}`,
);
console.log(
  `[5/10] 検索: totalMatched=${firstResult?.totalMatched}` +
    ` / returned=${firstResult?.returned} / 順序=${digest(firstResult)}`,
);
console.log(
  `[6/10] sampling: 呼び出し=${samplingCalls} 回` +
    ` / summarySource=${firstResult?.summarySource} / model=${firstResult?.model}`,
);
console.log(`[7/10] 要約の1行目: ${(firstResult?.summary ?? "").split("\n")[0]}`);

const careful = await summarize({ query: "連絡", directory: "faq", mode: "careful" });
console.log(
  `[8/10] mode="careful": ${(careful.structuredContent?.summary ?? "").split("\n")[0]}` +
    ` / elicitation 呼び出し=${elicitationCalls} 回`,
);

// roots を差し替えて list_changed を送る（キャッシュが捨てられるかの確認）
currentRoots = [{ uri: `file://${docsRoot}/guides`, name: "手順書" }];
await client.sendRootsListChanged();
await sleep(30); // 通知は応答が返らないので、届くまで少し待つ（セッション8）
const afterChange = await summarize({ query: "連絡" });
console.log(
  `[9/10] roots 変更後: scopeDirectories=${afterChange.structuredContent?.scopeDirectories.join(", ")}` +
    ` / totalMatched=${afterChange.structuredContent?.totalMatched}` +
    ` / 順序=${digest(afterChange.structuredContent)}`,
);

// 公開ディレクトリの外だけを申告する（境界を広げようとするケース）
currentRoots = [{ uri: "file:///tmp", name: "tmp" }];
await client.sendRootsListChanged();
await sleep(30);
const outside = await summarize({ query: "連絡" });
const search = (await client.callTool({
  name: "search_documents",
  arguments: { query: "連絡" },
})) as { structuredContent?: { totalMatched: number } };
console.log(
  `[10/10] roots が公開ディレクトリの外だけ: summarize は isError=${outside.isError === true}` +
    ` / search_documents は roots を見ないので totalMatched=${search.structuredContent?.totalMatched}`,
);

await client.close();
await server.close();
console.log("OK: sampling / roots / elicitation の 3 機能が期待どおりに動いています");
