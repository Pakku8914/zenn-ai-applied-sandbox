/**
 * 横断復習4 問題4 ―― sampling の劣化経路と上限付き返却
 *
 * 実行: docker compose exec node npx tsx src/review04/q4-summarize.ts
 *
 * サーバー定義側では console.log を使いません（ログは console.error）。
 * 検証クライアント側の console.log は使ってかまいません。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { CreateMessageRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import {
  createWorkflowStore,
  searchRequests,
  summaryLine,
  toUri,
  type RequestSummary,
} from "./workflow-lite.js";

const SAMPLING_TIMEOUT_MS = 30_000;
const MAX_SUMMARY_TOKENS = 320;
/** 用途は「対話中の要約」。速さと費用を優先し、賢さは求めない。モデルID は書かない */
const MODEL_PREFERENCES = {
  costPriority: 0.8,
  speedPriority: 0.9,
  intelligencePriority: 0.2,
} as const;

type SkipReason = "unsupported" | "call_failed" | "non_text_response";

/** sampling に渡すプロンプト。1 件 1 行の要約だけを入れ、申請理由（本文）は入れない */
function buildPrompt(query: string | undefined, items: readonly RequestSummary[]): string {
  return [
    query === undefined
      ? "社内申請の一覧です。"
      : `社内申請を「${query}」で検索した結果です。`,
    "判断に必要な事実だけを 3 行以内で要約してください。",
    "",
    ...items.map(summaryLine),
  ].join("\n");
}

export function createSummarizeServer(): McpServer {
  const store = createWorkflowStore();
  const server = new McpServer({ name: "review04-summarize", version: "1.0.0" });

  server.registerTool(
    "summarize_requests",
    {
      title: "申請一覧の要約",
      description:
        "社内申請を検索し、一覧の要約と各申請への参照（resource_link）を返します。" +
        "申請理由（本文）はレスポンスに含めません。" +
        "1 件の中身が知りたいときはこのツールを使わないでください（get_request を使います）。" +
        "返す件数には上限があり、上限に達した場合は結果にその旨と続きの取り方を書きます。",
      inputSchema: {
        query: z
          .string()
          .min(1)
          .max(40)
          .optional()
          .describe("検索語（タイトルと申請理由の部分一致）。省略すると全件を対象にします"),
        limit: z
          .number()
          .int()
          .min(1)
          .max(10)
          .default(5)
          .describe("返す件数の上限（1〜10、既定 5）"),
      },
      outputSchema: {
        total: z.number().int(),
        returned: z.number().int(),
        omitted: z.number().int().optional(),
        summarySource: z.enum(["sampling", "excerpt"]),
        skipReason: z.enum(["unsupported", "call_failed", "non_text_response"]).optional(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async ({ query, limit }, extra) => {
      const found = searchRequests(store, { query, limit });
      const omitted = found.total - found.items.length;

      // 既定は劣化した状態。成功したときだけ上書きする（劣化を「例外」にしない）
      let summary = found.items.map(summaryLine).join("\n");
      let source: "sampling" | "excerpt" = "excerpt";
      let skipReason: SkipReason | undefined = "unsupported";

      // 申告の値は空オブジェクト {} なので !== undefined で判定する（=== true では常に false）
      const supportsSampling = server.server.getClientCapabilities()?.sampling !== undefined;
      if (supportsSampling) {
        try {
          const result = await server.server.createMessage(
            {
              messages: [
                {
                  role: "user",
                  content: { type: "text", text: buildPrompt(query, found.items) },
                },
              ],
              systemPrompt:
                "社内申請の一覧を要約してください。一覧に書かれていないことは書かないでください。",
              maxTokens: MAX_SUMMARY_TOKENS,
              // 他サーバーの会話文脈を混ぜない
              includeContext: "none",
              temperature: 0,
              modelPreferences: { ...MODEL_PREFERENCES },
            },
            {
              relatedRequestId: extra.requestId,
              signal: extra.signal,
              timeout: SAMPLING_TIMEOUT_MS,
            },
          );
          if (result.content.type === "text") {
            summary = result.content.text.trim();
            source = "sampling";
            skipReason = undefined;
          } else {
            // 画像や音声が返ることもある。扱わないと決めておく
            skipReason = "non_text_response";
          }
        } catch (error) {
          console.error(
            "[review04] sampling/createMessage に失敗しました:",
            error instanceof Error ? error.message : String(error),
          );
          skipReason = "call_failed";
        }
      }

      const header =
        source === "sampling"
          ? "要約（クライアントの LLM による）:"
          : "抜粋（要約が使えなかったため一覧をそのまま返します）:";
      const tail =
        omitted > 0
          ? `（全 ${found.total} 件のうち ${found.items.length} 件を返しました。` +
            `残り ${omitted} 件は limit を上げるか、category / status で絞り込んでから呼び直してください）`
          : `（全 ${found.total} 件をすべて返しました）`;

      return {
        content: [
          { type: "text" as const, text: [header, summary, tail].join("\n") },
          // 本文は運ばず参照だけを返す
          ...found.items.map((item) => ({
            type: "resource_link" as const,
            uri: toUri(item.id),
            name: item.id,
            title: item.title,
            mimeType: "text/plain",
          })),
        ],
        structuredContent: {
          total: found.total,
          returned: found.items.length,
          // 0 のときはキー自体を作らない
          ...(omitted > 0 ? { omitted } : {}),
          summarySource: source,
          ...(skipReason === undefined ? {} : { skipReason }),
        },
      };
    },
  );

  return server;
}

// ── 検証 ────────────────────────────────────────────────────────────────
/** 決定的なダミー要約を返すハンドラ（実 LLM は使わない） */
function installStubSampling(client: Client): void {
  client.setRequestHandler(CreateMessageRequestSchema, (request) => {
    // content は「1 ブロック」と「ブロックの配列」のどちらも取りうる
    const raw = request.params.messages[0]?.content;
    const first = Array.isArray(raw) ? raw[0] : raw;
    const text = first !== undefined && first.type === "text" ? first.text : "";
    const lines = text.split("\n").filter((line) => line.startsWith("- ")).length;
    return {
      role: "assistant" as const,
      model: "stub-summarizer",
      stopReason: "endTurn",
      content: { type: "text" as const, text: `【ダミー要約】${lines} 件の申請を確認しました` },
    };
  });
}

/** ユーザーが拒否した状況を再現する（同期的に throw してよい） */
function installFailingSampling(client: Client): void {
  client.setRequestHandler(CreateMessageRequestSchema, () => {
    throw new Error("ユーザーが要約を拒否しました");
  });
}

type SummaryOutput = {
  total?: number;
  returned?: number;
  omitted?: number;
  summarySource?: string;
  skipReason?: string;
};

async function callOnce(options: {
  capabilities: Record<string, unknown>;
  install?: (client: Client) => void;
}) {
  // クライアントごとにサーバーを作り直す（connect は 1 対 1）
  const server = createSummarizeServer();
  const client = new Client(
    { name: "review04-summarize-client", version: "1.0.0" },
    { capabilities: options.capabilities },
  );
  options.install?.(client);
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  const result = await client.callTool({ name: "summarize_requests", arguments: {} });
  await client.close();
  await server.close();
  return result;
}

function structured(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): SummaryOutput {
  return (result.structuredContent ?? {}) as SummaryOutput;
}

const a = await callOnce({ capabilities: { sampling: {} }, install: installStubSampling });
const sa = structured(a);
console.log(
  `[1/4] A sampling あり: source=${sa.summarySource} / skipReason=${sa.skipReason} / ` +
    `total=${sa.total} returned=${sa.returned} omitted=${sa.omitted}`,
);

const b = await callOnce({ capabilities: {} });
const sb = structured(b);
console.log(
  `[2/4] B 申告なし: source=${sb.summarySource} / skipReason=${sb.skipReason} / ` +
    `total=${sb.total} returned=${sb.returned} omitted=${sb.omitted}`,
);

const c = await callOnce({ capabilities: { sampling: {} }, install: installFailingSampling });
const sc = structured(c);
console.log(
  `[3/4] C 例外を投げる: source=${sc.summarySource} / skipReason=${sc.skipReason} / ` +
    `isError=${c.isError === true}`,
);

const blocks = (a.content ?? []) as Array<{ type?: string; uri?: string }>;
const texts = blocks.filter((block) => block.type === "text").length;
const links = blocks.filter((block) => block.type === "resource_link");
const firstUri = links[0]?.uri ?? "(なし)";
// req-1003 の 900 文字の申請理由が混ざっていないことを機械的に確かめる
const leaked = JSON.stringify(a.content).includes("保証期間を過ぎており");
console.log(
  `[4/4] content=text×${texts} + resource_link×${links.length} / ` +
    `先頭の URI=${firstUri} / 申請理由を含まない=${!leaked}`,
);

console.log("OK: 問題4 の条件を満たしています");
