/**
 * 同じ 6 ツールを「素直に」実装した Bad 版（計測の対照）
 *
 * 実行： 直接は実行しません。measure-responses.ts から使います。
 *
 * ツールの粒度はセッション10 の Good と同じです。違うのは返し方だけです。
 *   ・API のレスポンスをそのまま JSON.stringify して返す（本文・履歴・添付も全部）
 *   ・返す量に上限がない（limit を無視する）
 *   ・失敗を isError で表明しない
 *   ・例外の中身をそのまま返す
 *
 * 本番では書かないでください。何が起きるかを数字で見るためだけの実装です。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import {
  addComment,
  applyDecision,
  applySubmit,
  previewDecision,
  previewSubmit,
  saveRequest,
  searchRequests,
  type Category,
  type Decision,
  type Status,
  type Store,
  type WorkflowRequest,
} from "../session10/data.js";
import { createBudgetApi, createBulkyStore, type BudgetApi } from "./fixtures.js";

export type VerboseServerOptions = { store?: Store; budgetApi?: BudgetApi };

/** JSON をそのままテキストで返す（Bad の共通の返し方） */
function raw(value: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(value) }] };
}

export function createVerboseServer(options: VerboseServerOptions = {}): McpServer {
  const store = options.store ?? createBulkyStore();
  const budgetApi = options.budgetApi ?? createBudgetApi();
  const server = new McpServer({ name: "workflow-requests-verbose", version: "1.0.0" });

  server.registerTool(
    "search_requests",
    {
      title: "申請検索",
      description: "申請を検索して一覧を返します。",
      inputSchema: {
        query: z.string().optional(),
        status: z.array(z.string()).optional(),
        category: z.string().optional(),
        applicantId: z.string().optional(),
        minAmountYen: z.number().optional(),
        limit: z.number().optional(),
        cursor: z.string().optional(),
      },
    },
    async (args) => {
      // limit を無視して全部返す。1 件あたりも API のオブジェクトをそのまま返す
      const result = searchRequests(store, {
        query: args.query,
        status: args.status as Status[] | undefined,
        category: args.category as Category | undefined,
        applicantId: args.applicantId,
        minAmountYen: args.minAmountYen,
        limit: 1000,
      });
      const full = result.items
        .map((item) => store.requests.get(item.id))
        .filter((request): request is WorkflowRequest => request !== undefined);
      return raw({ total: result.total, items: full });
    },
  );

  server.registerTool(
    "get_request",
    {
      title: "申請詳細",
      description: "申請 1 件の詳細を返します。",
      inputSchema: { requestId: z.string(), include: z.array(z.string()).optional() },
    },
    async ({ requestId }) => {
      const request = store.requests.get(requestId);
      // include を無視して常に全部返す。見つからない場合も isError を立てない
      if (request === undefined) return raw({ error: "not found", requestId });
      return raw(request);
    },
  );

  server.registerTool(
    "save_request",
    {
      title: "申請保存",
      description: "申請を作成または更新します。",
      inputSchema: {
        requestId: z.string().optional(),
        title: z.string().optional(),
        category: z.string().optional(),
        amountYen: z.number().optional(),
        body: z.string().optional(),
      },
    },
    async (args) =>
      raw(
        saveRequest(store, {
          requestId: args.requestId,
          title: args.title,
          category: args.category as Category | undefined,
          amountYen: args.amountYen,
          body: args.body,
        }),
      ),
  );

  server.registerTool(
    "submit_request",
    {
      title: "申請提出",
      description: "申請を提出します。",
      inputSchema: {
        requestId: z.string(),
        confirm: z.boolean().optional(),
        previewToken: z.string().optional(),
      },
    },
    async ({ requestId, confirm }) => {
      try {
        const request = store.requests.get(requestId);
        await budgetApi.check((request?.category ?? "expense") as Category, request?.amountYen ?? 0);
      } catch (error) {
        // 例外の文面とスタックトレースをそのまま返している。しかも isError を立てていない
        return {
          content: [
            { type: "text" as const, text: `エラー: ${String(error)}\n${(error as Error).stack ?? ""}` },
          ],
        };
      }
      if (confirm === true) return raw(applySubmit(store, requestId));
      return raw(previewSubmit(store, requestId));
    },
  );

  server.registerTool(
    "decide_request",
    {
      title: "申請決裁",
      description: "申請を承認・却下・差し戻しします。",
      inputSchema: {
        requestId: z.string(),
        decision: z.string(),
        comment: z.string().optional(),
        confirm: z.boolean().optional(),
        previewToken: z.string().optional(),
      },
    },
    async ({ requestId, decision, comment, confirm }) => {
      const value = decision as Decision;
      if (confirm === true) return raw(applyDecision(store, requestId, value, comment));
      return raw(previewDecision(store, requestId, value, comment));
    },
  );

  server.registerTool(
    "comment_on_request",
    {
      title: "コメント投稿",
      description: "申請にコメントを追加します。",
      inputSchema: { requestId: z.string(), body: z.string(), links: z.array(z.string()).optional() },
    },
    async ({ requestId, body, links }) => {
      const result = addComment(store, requestId, body, links ?? []);
      // 成功しても失敗しても、申請オブジェクト全体を返してしまう
      return raw({ result, request: store.requests.get(requestId) });
    },
  );

  return server;
}
