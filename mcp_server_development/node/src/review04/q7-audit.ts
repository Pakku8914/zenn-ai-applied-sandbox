/**
 * 横断復習4 問題7 ―― 機械的に検査できる 8 項目のセルフレビュー・ハーネス
 *
 * 実行: docker compose exec node npx tsx src/review04/q7-audit.ts
 *
 * 検査は tools/list と tools/call の結果だけで行います。
 * サーバー内部の関数を直接呼ばないのが要点です（公開されている定義しか見ない）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import {
  SCOPE_APPROVE,
  SCOPE_READ,
  SCOPE_WRITE,
  TOOL_SCOPES,
  leaksInternalDetail,
  measureTools,
  scopeFailure,
  toolFailure,
} from "./support.js";
import {
  CATEGORIES,
  DECISIONS,
  STATUSES,
  createWorkflowStore,
  decideRequest,
  searchRequests,
  summaryLine,
} from "./workflow-lite.js";

const MAX_TOOLS = 6;
const MAX_DEFINITION_CHARS = 6_000;
const ANNOTATION_KEYS = [
  "readOnlyHint",
  "destructiveHint",
  "idempotentHint",
  "openWorldHint",
] as const;
/** 取り消せない操作を示す語。注釈は間違っていることがあるので、名前でも拾う */
const IRREVERSIBLE_HINTS = ["approve", "reject", "decide", "delete", "purge", "cancel"] as const;
/** 選択肢を閉じるべき引数 */
const CLOSED_ARGS = ["category", "status", "decision"] as const;

const READ_ONLY_ANNOTATIONS = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
} as const;

// ── 検査対象のサーバー ──────────────────────────────────────────────────
export type Mode = "good" | "bad";

function createGoodServer(grantedScopes: readonly string[]): McpServer {
  const store = createWorkflowStore();
  const server = new McpServer({ name: "review04-good", version: "1.0.0" });

  server.registerTool(
    "search_requests",
    {
      title: "申請を検索",
      description:
        "社内申請を条件で絞り込み、1 件 1 行の一覧を返します。申請理由は含めません。" +
        "申請 ID が分かっているときはこのツールを使わないでください（get_request を使います）。",
      inputSchema: {
        category: z.enum(CATEGORIES).optional().describe("申請区分で絞り込む"),
        status: z.array(z.enum(STATUSES)).optional().describe("状態で絞り込む（複数指定可）"),
        limit: z.number().int().min(1).max(20).default(10).describe("返す件数の上限（1〜20、既定 10）"),
      },
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async ({ category, status, limit }) => {
      const found = searchRequests(store, { category, status, limit });
      return {
        content: [{ type: "text" as const, text: found.items.map(summaryLine).join("\n") }],
      };
    },
  );

  server.registerTool(
    "get_request",
    {
      title: "申請の詳細",
      description:
        "申請 1 件の詳細を返します。include でコメントと履歴を追加できます。" +
        "条件で探したいときは代わりに search_requests を使ってください。",
      inputSchema: {
        requestId: z.string().min(1).max(32).describe("申請 ID（例: req-1003）"),
        include: z
          .array(z.enum(["comments", "history"]))
          .default([])
          .describe("追加で返すセクション"),
      },
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async ({ requestId }) => {
      const row = store.requests.get(requestId);
      return {
        content: [
          { type: "text" as const, text: row === undefined ? "該当なし" : `${row.id} ${row.title}` },
        ],
      };
    },
  );

  server.registerTool(
    "create_request",
    {
      title: "申請を起票",
      description:
        "下書きの申請を 1 件作ります。既存の申請を直したいときはこのツールを使わないでください。",
      inputSchema: {
        title: z.string().min(1).max(80).describe("申請の件名"),
        category: z.enum(CATEGORIES).describe("申請区分"),
        reason: z.string().min(10).max(1_000).describe("申請理由（10〜1000 文字）"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ title }) => {
      const denied = scopeFailure("create_request", grantedScopes);
      if (denied !== undefined) return toolFailure(denied);
      return { content: [{ type: "text" as const, text: `下書き「${title}」を作成しました。` }] };
    },
  );

  server.registerTool(
    "decide_request",
    {
      title: "申請を決裁",
      description:
        "申請を承認または却下します。取り消せない操作なので二段階です。" +
        "confirm を省略すると確認だけを行い previewToken を返します。" +
        "下書きを取り下げたいときはこのツールを使わないでください。",
      inputSchema: {
        requestId: z.string().min(1).max(32).describe("申請 ID"),
        decision: z.enum(DECISIONS).describe("approve または reject"),
        reason: z.string().min(10).max(200).describe("決裁の理由（10〜200 文字）"),
        confirm: z.boolean().default(false).describe("true のときだけ実際に決裁します"),
        previewToken: z.string().optional().describe("ドライランで返された previewToken"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ requestId, decision, confirm }) => {
      const denied = scopeFailure("decide_request", grantedScopes);
      if (denied !== undefined) return toolFailure(denied);
      if (!confirm) {
        return { content: [{ type: "text" as const, text: "ドライラン（previewToken: dummy）" }] };
      }
      decideRequest(store, requestId, decision);
      return { content: [{ type: "text" as const, text: `${requestId} を決裁しました。` }] };
    },
  );

  return server;
}

/** 問題1 のレビュー対象を写した 7 本。ハーネスが欠陥を捕まえられるかを試すための対照 */
function createBadServer(): McpServer {
  const store = createWorkflowStore();
  const server = new McpServer({ name: "review04-bad", version: "1.0.0" });
  const ok = async () => ({ content: [{ type: "text" as const, text: "ok" }] });

  const define = (
    name: string,
    title: string,
    description: string,
    inputSchema: Record<string, z.ZodTypeAny>,
    readOnly: boolean,
  ): void => {
    server.registerTool(
      name,
      { title, description, inputSchema, annotations: { readOnlyHint: readOnly } },
      ok,
    );
  };

  define(
    "get_requests",
    "申請一覧",
    "GET /api/requests を呼び出します。申請の一覧を返します。",
    {
      status: z.string().optional().describe("状態"),
      category: z.string().optional().describe("区分"),
      page: z.number().optional().describe("ページ番号"),
      perPage: z.number().optional().describe("1 ページの件数"),
    },
    true,
  );
  define("get_request_by_id", "申請詳細", "GET /api/requests/{id} を呼び出します。", { id: z.string() }, true);
  define("get_request_comments", "申請コメント", "GET /api/requests/{id}/comments を呼び出します。", { id: z.string() }, true);
  define("get_request_history", "申請履歴", "GET /api/requests/{id}/history を呼び出します。", { id: z.string() }, true);
  define(
    "post_request",
    "申請作成",
    "POST /api/requests を呼び出します。",
    { title: z.string(), category: z.string() },
    false,
  );
  server.registerTool(
    "put_request_approve",
    {
      title: "申請承認",
      description: "POST /api/requests/{id}/approve を呼び出します。",
      inputSchema: { id: z.string(), comment: z.string().optional() },
      annotations: { readOnlyHint: true, idempotentHint: true },
    },
    async ({ id }) => {
      decideRequest(store, id, "approve");
      return { content: [{ type: "text" as const, text: "承認しました" }] };
    },
  );
  define("delete_request", "申請削除", "DELETE /api/requests/{id} を呼び出します。", { id: z.string(), force: z.boolean().optional() }, false);

  return server;
}

export function createAuditTarget(options: {
  mode: Mode;
  grantedScopes: readonly string[];
}): McpServer {
  return options.mode === "good" ? createGoodServer(options.grantedScopes) : createBadServer();
}

// ── ハーネス ────────────────────────────────────────────────────────────
type ToolDefinition = {
  name: string;
  description?: string;
  annotations?: Record<string, unknown>;
  inputSchema?: unknown;
};

type CheckResult = { id: number; label: string; ok: boolean; detail: string };

function propertiesOf(tool: ToolDefinition): Record<string, Record<string, unknown>> {
  const schema = (tool.inputSchema ?? {}) as { properties?: Record<string, unknown> };
  const out: Record<string, Record<string, unknown>> = {};
  for (const [key, value] of Object.entries(schema.properties ?? {})) {
    if (typeof value === "object" && value !== null) {
      out[key] = value as Record<string, unknown>;
    }
  }
  return out;
}

/** enum / items.enum / anyOf の中の enum を許容する（スキーマ生成の差を吸収する） */
function isClosed(prop: Record<string, unknown>): boolean {
  if (Array.isArray(prop["enum"])) return true;
  const items = prop["items"];
  if (typeof items === "object" && items !== null) {
    if (isClosed(items as Record<string, unknown>)) return true;
  }
  const anyOf = prop["anyOf"];
  if (Array.isArray(anyOf)) {
    return anyOf.some(
      (entry) =>
        typeof entry === "object" && entry !== null && isClosed(entry as Record<string, unknown>),
    );
  }
  return false;
}

function names(list: readonly string[], limit = 3): string {
  if (list.length <= limit) return list.join(", ");
  return `${list.slice(0, limit).join(", ")} 他 ${list.length - limit} 本`;
}

export async function auditServer(options: {
  client: Client;
  deniedClient: Client;
  /** 取り消せない操作を権限なしで叩くための引数（サーバーごとに 1 つ用意する） */
  probe: { name: string; arguments: Record<string, unknown> };
}): Promise<CheckResult[]> {
  const tools = (await options.client.listTools()).tools as ToolDefinition[];
  const results: CheckResult[] = [];

  // [1] 本数
  results.push({
    id: 1,
    label: `ツール本数 ${MAX_TOOLS} 以下`,
    ok: tools.length <= MAX_TOOLS,
    detail: `${tools.length} 本`,
  });

  // [2] 注釈 4 つの明示
  const missingAnnotations = tools
    .filter((tool) => {
      const annotations = tool.annotations ?? {};
      return ANNOTATION_KEYS.some((key) => annotations[key] === undefined);
    })
    .map((tool) => tool.name);
  results.push({
    id: 2,
    label: "注釈 4 つの明示",
    ok: missingAnnotations.length === 0,
    detail: names(missingAnnotations),
  });

  // [3] スコープ表への登録
  const unregistered = tools.filter((tool) => TOOL_SCOPES[tool.name] === undefined).map((t) => t.name);
  results.push({
    id: 3,
    label: "スコープ表への登録",
    ok: unregistered.length === 0,
    detail: names(unregistered),
  });

  // [4] 取り消せない操作の二段階。注釈と名前の両方から拾う（注釈は間違っていることがある）
  const irreversible = tools.filter((tool) => {
    if ((tool.annotations ?? {})["destructiveHint"] === true) return true;
    return IRREVERSIBLE_HINTS.some((hint) => tool.name.includes(hint));
  });
  const missingTwoPhase = irreversible
    .filter((tool) => {
      const props = propertiesOf(tool);
      return props["confirm"] === undefined || props["previewToken"] === undefined;
    })
    .map((tool) => tool.name);
  results.push({
    id: 4,
    label: "取り消せない操作の二段階",
    ok: missingTwoPhase.length === 0,
    detail: names(missingTwoPhase),
  });

  // [5] 説明文の「いつ使わないか」
  const missingBoundary = tools
    .filter((tool) => {
      const text = tool.description ?? "";
      return !text.includes("使わない") && !text.includes("代わりに");
    })
    .map((tool) => tool.name);
  results.push({
    id: 5,
    label: "説明文の「いつ使わないか」",
    ok: missingBoundary.length === 0,
    detail: names(missingBoundary),
  });

  // [6] 定義サイズ
  const measured = measureTools(tools);
  results.push({
    id: 6,
    label: `定義サイズ ${MAX_DEFINITION_CHARS} chars 以内`,
    ok: measured.totalChars <= MAX_DEFINITION_CHARS,
    detail: `${tools.length} 本 / ${measured.totalChars} chars / 約 ${measured.totalTokens} tokens`,
  });

  // [7] 閉じるべき引数の列挙化
  const openArgs: string[] = [];
  for (const tool of tools) {
    const props = propertiesOf(tool);
    for (const key of CLOSED_ARGS) {
      const prop = props[key];
      if (prop !== undefined && !isClosed(prop)) openArgs.push(`${tool.name}.${key}`);
    }
  }
  results.push({
    id: 7,
    label: "閉じるべき引数の列挙化",
    ok: openArgs.length === 0,
    detail: names(openArgs),
  });

  // [8] 権限不足の文面（3 要素 ＋ 内部情報の露出なし）
  let detail8 = "";
  let ok8 = false;
  try {
    const result = await options.deniedClient.callTool({
      name: options.probe.name,
      arguments: options.probe.arguments,
    });
    const blocks = (result.content ?? []) as Array<{ type?: string; text?: string }>;
    const text = blocks.find((block) => block.type === "text")?.text ?? "";
    const isError = result.isError === true;
    const hasCode = /^\[[a-z_]+\]/.test(text.trim());
    const hasNext = text.includes("次の一手:");
    const hasRetry = text.includes("再試行:");
    const leaks = leaksInternalDetail(text);
    ok8 = isError && hasCode && hasNext && hasRetry && !leaks;
    detail8 = `isError=${isError} / 分類=${hasCode} / 次の一手=${hasNext} / 再試行=${hasRetry} / 露出=${leaks}`;
  } catch (error) {
    detail8 = `例外 ${error instanceof Error ? error.name : String(error)}`;
  }
  results.push({ id: 8, label: "権限不足の文面", ok: ok8, detail: detail8 });

  return results;
}

// ── 実行 ────────────────────────────────────────────────────────────────
async function connect(mode: Mode, grantedScopes: readonly string[]): Promise<Client> {
  const server = createAuditTarget({ mode, grantedScopes });
  const client = new Client({ name: "review04-audit-client", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return client;
}

async function report(
  mode: Mode,
  probe: { name: string; arguments: Record<string, unknown> },
): Promise<void> {
  // 検査8 は破壊的操作を叩くので、権限なしの接続は必ず別インスタンス（＝捨てられるデータ）にする
  const client = await connect(mode, [SCOPE_READ, SCOPE_WRITE, SCOPE_APPROVE]);
  const deniedClient = await connect(mode, [SCOPE_READ]);
  const results = await auditServer({ client, deniedClient, probe });
  console.log(`=== ${mode} ===`);
  for (const row of results) {
    console.log(`  [${row.id}] ${row.label}: ${row.ok ? "OK" : `NG（${row.detail}）`}`);
  }
  const passed = results.filter((row) => row.ok).length;
  const failed = results.filter((row) => !row.ok).map((row) => String(row.id));
  console.log(
    `  ${mode}: ${passed}/${results.length}` +
      (failed.length === 0 ? "" : `（失敗: ${failed.join(", ")}）`),
  );
  await client.close();
  await deniedClient.close();
}

await report("good", {
  name: "decide_request",
  arguments: {
    requestId: "req-1003",
    decision: "approve",
    reason: "内容と金額を確認したため承認します。",
  },
});
await report("bad", { name: "put_request_approve", arguments: { id: "req-1003" } });

console.log("OK: 8 項目のセルフレビュー・ハーネスが動きました");
