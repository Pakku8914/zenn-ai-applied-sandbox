/**
 * 部分成功の表現（一括決裁の隔離デモ）
 *
 * 実行： docker compose exec node npx tsx src/session11/partial-success.ts
 *
 * このツールは本番の 6 本には入れません（粒度の判断はセッション10）。
 * 部分成功の返し方だけを取り出して確認するためのデモです。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { DECISIONS, applyDecision, type Decision, type Status } from "../session10/data.js";
import { toolFailure, type ToolFailure } from "./errors.js";
import { createBulkyStore } from "./fixtures.js";
import { BUDGET, summarizeBatch, type ItemOutcome } from "./respond.js";

const store = createBulkyStore();
const server = new McpServer({ name: "workflow-batch", version: "1.0.0" });

function stateFailure(requestId: string, status: Status | undefined): ToolFailure | undefined {
  if (status === undefined) {
    return {
      code: "not_found",
      what: "この ID の申請は存在しません。",
      next: "search_requests で ID を確認してください。",
      retryable: false,
    };
  }
  if (status !== "in_review") {
    return {
      code: "invalid_state",
      what: `状態が ${status} のため決裁できません。`,
      next: "決裁できるのは in_review の申請だけです。この ID は一括処理の対象から外してください。",
      retryable: false,
    };
  }
  return undefined;
}

server.registerTool(
  "decide_requests",
  {
    title: "複数の申請をまとめて決裁する",
    description:
      `審査中の申請を最大 ${BUDGET.batchItems} 件までまとめて決裁します。` +
      "1 件ずつ処理し、途中で失敗しても残りは続行します（部分成功します）。" +
      "結果には成功した ID と失敗した ID の両方が含まれます。" +
      "失敗した ID だけを直してから呼び直してください（成功分は確定済みです）。",
    inputSchema: {
      requestIds: z
        .array(z.string().regex(/^req-\d{4}$/))
        .min(1)
        .max(BUDGET.batchItems)
        .describe(`決裁する申請 ID（1〜${BUDGET.batchItems} 件）`),
      decision: z.enum(DECISIONS).describe("全件に同じ決裁を適用します"),
      comment: z.string().min(1).max(500).optional().describe("決裁理由（approve 以外では必須）"),
      confirm: z.boolean().default(false).describe("false（既定）はドライラン"),
    },
    outputSchema: {
      succeeded: z.number().int(),
      failed: z.number().int(),
      items: z.array(
        z.object({
          id: z.string(),
          ok: z.boolean(),
          code: z.string().optional(),
          retryable: z.boolean().optional(),
        }),
      ),
      retryableIds: z.array(z.string()),
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false,
    },
  },
  async ({ requestIds, decision, comment, confirm }) => {
    if (decision !== "approve" && (comment === undefined || comment.trim() === "")) {
      // 全件に共通する引数の不備は、1 件も処理せずに失敗として返す
      return toolFailure({
        code: "invalid_argument",
        what: `decision="${decision}" では comment（理由）が必須です。`,
        next: "理由を comment に指定して呼び直してください。まだ 1 件も処理していません。",
        retryable: false,
      });
    }

    const outcomes: ItemOutcome[] = [];
    for (const requestId of requestIds) {
      const failure = stateFailure(requestId, store.requests.get(requestId)?.status);
      if (failure !== undefined) {
        outcomes.push({ id: requestId, ok: false, failure });
        continue;
      }
      if (!confirm) {
        outcomes.push({ id: requestId, ok: true, detail: "決裁できます（ドライラン）" });
        continue;
      }
      const applied = applyDecision(store, requestId, decision as Decision, comment);
      if (!applied.ok) {
        outcomes.push({
          id: requestId,
          ok: false,
          failure: {
            code: "internal",
            what: "決裁の適用に失敗しました。",
            next: "この ID だけを decide_request で個別に処理してください。",
            retryable: false,
          },
        });
        continue;
      }
      outcomes.push({
        id: requestId,
        ok: true,
        detail: `${applied.stepLabel} / 状態: ${applied.status}`,
      });
    }

    const summary = summarizeBatch(confirm ? "一括決裁" : "一括決裁（ドライラン）", outcomes);

    // ここが部分成功の判断：1 件でも成功していれば isError は立てない
    const allFailed = summary.succeeded === 0;
    return {
      content: [{ type: "text", text: summary.text }],
      structuredContent: {
        succeeded: summary.succeeded,
        failed: summary.failed,
        items: summary.items,
        retryableIds: summary.retryableIds,
      },
      ...(allFailed ? { isError: true } : {}),
    };
  },
);

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "partial-success", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

function show(label: string, result: { content?: unknown; isError?: boolean; [key: string]: unknown }): void {
  const text = (result.content as Array<{ text?: string }> | undefined)?.[0]?.text ?? "";
  console.log(`\n[${label}] isError=${result.isError === true}`);
  console.log(text);
}

// 3 件成功・2 件失敗（req-1001 は draft、req-9999 は存在しない）
show(
  "一部成功",
  await client.callTool({
    name: "decide_requests",
    arguments: {
      requestIds: ["req-1002", "req-1003", "req-1011", "req-1001", "req-9999"],
      decision: "approve",
      confirm: true,
    },
  }),
);

// 全件失敗（すでに決裁済み・存在しない）
show(
  "全件失敗",
  await client.callTool({
    name: "decide_requests",
    arguments: { requestIds: ["req-1004", "req-9999"], decision: "approve", confirm: true },
  }),
);

await client.close();
await server.close();
