/**
 * 引数の改名を後方互換で行う実演
 *
 * 実行： docker compose exec node npx tsx src/session10/schema-evolution.ts
 *
 * v2  : applicant（旧・廃止予定）と applicantId（新）の両方を受ける
 * v3a : applicant を完全に削除した版（黙って壊れることの確認）
 * v3b : applicant を廃止マーカーとして残した版（明示的に案内する）
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { createStore, searchRequests, type Store } from "./data.js";

type Variant = "v2" | "v3a" | "v3b";

function buildServer(variant: Variant, store: Store): McpServer {
  const server = new McpServer({ name: `workflow-${variant}`, version: "1.0.0" });

  /** 変種ごとに入力スキーマを組み替える */
  const inputSchema: z.ZodRawShape =
    variant === "v2"
      ? {
          applicantId: z.string().optional().describe("申請者のユーザー ID（u-001 の形式）"),
          applicant: z
            .string()
            .optional()
            .describe("【廃止予定】applicantId に置き換えてください。当面は同じ意味で動作します"),
        }
      : variant === "v3a"
        ? {
            // 旧引数を完全に削除した版。送られても Zod が捨てるのでハンドラは気づけない
            applicantId: z.string().optional().describe("申請者のユーザー ID（u-001 の形式）"),
          }
        : {
            applicantId: z.string().optional().describe("申請者のユーザー ID（u-001 の形式）"),
            applicant: z
              .string()
              .optional()
              .describe("【廃止済み】この引数は使えません。applicantId を指定してください"),
          };

  server.registerTool(
    "search_requests",
    {
      title: "申請を探す",
      description: "申請を条件で絞り込み、要約の一覧を返します。",
      inputSchema,
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async (args: Record<string, unknown>) => {
      const params = args as { applicantId?: string; applicant?: string };

      if (variant === "v3b" && params.applicant !== undefined) {
        return {
          content: [
            {
              type: "text",
              text:
                "引数 applicant は廃止されました。applicantId に同じ値を指定して呼び直してください" +
                "（例: { applicantId: \"u-001\" }）。",
            },
          ],
          isError: true,
        };
      }

      if (variant === "v2" && params.applicant !== undefined && params.applicantId !== undefined) {
        return {
          content: [
            {
              type: "text",
              text: "applicant と applicantId は同時に指定できません。applicantId だけを使ってください。",
            },
          ],
          isError: true,
        };
      }

      if (variant === "v2" && params.applicant !== undefined) {
        // 旧名で来たことを運用側が把握できるように記録する（stdout は使わない）
        console.error("[deprecated] search_requests: applicant は applicantId に置き換えてください");
      }

      const applicantId = params.applicantId ?? (variant === "v2" ? params.applicant : undefined);
      const result = searchRequests(store, { ...(applicantId === undefined ? {} : { applicantId }), limit: 50 });
      return {
        content: [{ type: "text", text: `${result.total} 件` }],
      };
    },
  );
  return server;
}

async function callWith(variant: Variant, args: Record<string, unknown>): Promise<string> {
  const server = buildServer(variant, createStore());
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "schema-evolution", version: "1.0.0" });
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  const result = await client.callTool({ name: "search_requests", arguments: args });
  const first = (result.content as Array<{ text?: string }>)[0];
  const label = result.isError === true ? "isError" : "OK";
  await client.close();
  await server.close();
  return `${label}: ${first?.text ?? ""}`;
}

console.log(`[v2 ] 旧引数 applicant="u-001"      → ${await callWith("v2", { applicant: "u-001" })}`);
console.log(`[v2 ] 新引数 applicantId="u-001"    → ${await callWith("v2", { applicantId: "u-001" })}`);
console.log(
  `[v2 ] 両方指定                       → ${await callWith("v2", { applicant: "u-001", applicantId: "u-001" })}`,
);
console.log(`[v3a] 削除版に旧引数を送る          → ${await callWith("v3a", { applicant: "u-001" })}`);
console.log(`[v3b] 廃止マーカー版に旧引数を送る  → ${await callWith("v3b", { applicant: "u-001" })}`);
console.log("OK: スキーマ進化の実演が完了しました");
