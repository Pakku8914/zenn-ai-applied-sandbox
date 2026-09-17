/**
 * 横断復習4 問題2 ―― 失敗の 3 層を実測で検算する
 *
 * 実行: docker compose exec node npx tsx src/review04/q2-layers.ts
 *
 * クライアント側のスクリプトなので console.log を使ってかまいません
 * （禁止されているのは「サーバープロセスの stdout」だけです）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { EmptyResultSchema, ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import { toolFailure } from "./support.js";
import {
  STATUSES,
  createWorkflowStore,
  searchRequests,
  summaryLine,
  toUri,
} from "./workflow-lite.js";

const store = createWorkflowStore();
const server = new McpServer({ name: "review04-layers", version: "1.0.0" });

server.registerTool(
  "search_requests",
  {
    title: "申請を検索",
    description:
      "社内申請を条件で絞り込み、1 件 1 行の一覧を返します。" +
      "申請 ID が分かっているときはこのツールを使わないでください（get_request を使います）。",
    inputSchema: {
      status: z.array(z.enum(STATUSES)).optional().describe("状態で絞り込む（複数指定可）"),
      limit: z.number().int().min(1).max(10).default(5).describe("返す件数の上限（1〜10、既定 5）"),
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  },
  async ({ status, limit }) => {
    const found = searchRequests(store, { status, limit });
    return {
      content: [
        { type: "text" as const, text: `${found.total} 件中 ${found.items.length} 件を返します。` },
        ...found.items.map((item) => ({ type: "text" as const, text: summaryLine(item) })),
      ],
    };
  },
);

server.registerTool(
  "get_request",
  {
    title: "申請の詳細",
    description:
      "申請 1 件の詳細を返します。" +
      "条件で探したいときはこのツールを使わないでください（代わりに search_requests を使います）。",
    inputSchema: { requestId: z.string().describe("申請 ID（例: req-1003）") },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  },
  async ({ requestId }) => {
    const row = store.requests.get(requestId);
    if (row === undefined) {
      // 層3。文面はこちらで書けるので、AI が自力で回復できる 3 要素を入れる
      return toolFailure({
        code: "not_found",
        what: `申請 ${requestId} は見つかりませんでした。`,
        next: "search_requests で条件を指定して候補の ID を確認してから呼び直してください。",
        retryable: false,
      });
    }
    return {
      content: [{ type: "text" as const, text: `${row.id} ${row.title}（${row.status}）` }],
    };
  },
);

// リソースを 1 つ登録する。プロンプトは登録しない（ケース6 のため）
server.registerResource(
  "request",
  new ResourceTemplate("request://{id}", { list: undefined }),
  { title: "申請 1 件", description: "申請 1 件の要約を返します。", mimeType: "text/plain" },
  async (_uri, variables) => {
    const rawValue = variables["id"];
    const id = Array.isArray(rawValue) ? (rawValue[0] ?? "") : (rawValue ?? "");
    const row = store.requests.get(id);
    if (row === undefined) {
      // リソースの失敗は JSON-RPC エラー。isError はツールだけの仕組み（セッション6）
      throw new McpError(
        ErrorCode.InvalidParams,
        "その申請はありません。search_requests で ID を確認してください。",
      );
    }
    return {
      contents: [
        { uri: toUri(row.id), mimeType: "text/plain", text: `${row.id} ${row.title}` },
      ],
    };
  },
);

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "review04-layers-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

function firstText(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): string {
  const blocks = (result.content ?? []) as Array<{ type?: string; text?: string }>;
  return blocks.find((block) => block.type === "text")?.text ?? "";
}

/**
 * 本文が「SDK が組み立てたもの」か「自分で書いたもの」かを判定する。
 * 生の文面をそのまま出力すると SDK の版で変わってしまうので、分類だけを出します。
 */
function classify(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): string {
  const text = firstText(result).replace(/\s+/g, " ").trim();
  const sdk = /^MCP error (-?\d+)/.exec(text);
  if (sdk !== null) return `SDK が組み立てた文面（MCP error ${sdk[1]}）`;
  const own = /^\[([a-z_]+)\]/.exec(text);
  if (own !== null) return `自分で書いた文面（[${own[1]}]）`;
  return `その他（${text.slice(0, 24)}）`;
}

/** ツール呼び出しを「例外が飛んだか」まで含めて観測する */
async function observeTool(
  label: string,
  index: number,
  name: string,
  args: Record<string, unknown>,
): Promise<void> {
  try {
    const result = await client.callTool({ name, arguments: args });
    console.log(
      `[${index}/6] ${label}: 例外=なし / isError=${result.isError === true} / 本文=${classify(result)}`,
    );
  } catch (error) {
    console.log(`[${index}/6] ${label}: 例外=${describe(error)}`);
  }
}

function describe(error: unknown): string {
  if (error instanceof McpError) return `McpError code=${error.code}`;
  if (error instanceof Error) return `Error`;
  return String(error);
}

// ① 引数が列挙値の外 ―― 直感では層2 だが……
await observeTool("列挙値の外", 1, "search_requests", { status: ["審査中"] });
// ② 存在しないツール名
await observeTool("未知のツール名", 2, "approve_request", { requestId: "req-1003" });
// ③ 業務的な失敗
await observeTool("対象が存在しない", 3, "get_request", { requestId: "req-9999" });

// ④ リソースの読み取り失敗（ハンドラが McpError を投げる）
try {
  await client.readResource({ uri: "request://req-9999" });
  console.log("[4/6] リソースの読み取り失敗: 例外=なし（想定外）");
} catch (error) {
  console.log(`[4/6] リソースの読み取り失敗: 例外=${describe(error)}`);
}

// ⑤ サーバーが登録していないメソッド
try {
  await client.request({ method: "workflow/nonexistent", params: {} }, EmptyResultSchema);
  console.log("[5/6] 知らないメソッド: 例外=なし（想定外）");
} catch (error) {
  console.log(`[5/6] 知らないメソッド: 例外=${describe(error)}`);
}

// ⑥ サーバーが宣言していないサーバー機能（prompts を登録していない）
try {
  await client.listPrompts();
  console.log("[6/6] 宣言していないサーバー機能: 例外=なし（想定外）");
} catch (error) {
  console.log(
    `[6/6] 宣言していないサーバー機能: 例外=${describe(error)}（送信前にクライアントが停止）`,
  );
}

console.log(
  "OK: 層の境界は「引数が正しいか」ではなく「そのメソッドを受け付けられるか」でした",
);

await client.close();
await server.close();
