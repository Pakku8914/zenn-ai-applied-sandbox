/**
 * ❌ 学習用の Bad 実装です。実務でまねしないでください。
 *
 * 意図的に入れてある欠陥（本文の対比と練習問題で使います）
 *   ① archive_project に readOnlyHint: true（嘘の注釈）
 *   ② exportReportCSV に注釈がない（既定値で「破壊的」と解釈される）＋命名が不統一
 *   ③ summarize_hours の outputSchema と structuredContent が不一致
 *   ④ 失敗を isError なしのテキストで返している
 *   ⑤ 引数に形式指定も description もない
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import {
  archiveProject,
  buildReportRows,
  findProject,
  listMembers,
  summarizeHours,
  toCsv,
} from "./data.js";

export function createBadDashboardServer(): McpServer {
  const server = new McpServer({ name: "team-dashboard-bad", version: "0.2.0" });

  // これだけは正しい（比較の基準として置いています）
  server.registerTool(
    "list_members",
    {
      title: "メンバー一覧",
      description: "メンバーの一覧を返します。",
      inputSchema: {},
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async () => ({
      content: [{ type: "text", text: `メンバー ${listMembers().length} 名` }],
    }),
  );

  server.registerTool(
    "summarize_hours",
    {
      // ❌ title がない → ホストは name をそのまま表示する
      description: "稼働時間を集計します。", // ❌ いつ使うか・引数の形式が分からない
      inputSchema: {
        from: z.string(), // ❌ 形式指定も説明もない
        to: z.string(),
      },
      outputSchema: {
        totalHours: z.number(),
        members: z.array(z.object({ memberId: z.string(), totalHours: z.number() })),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ from, to }) => {
      const summary = summarizeHours({ from, to });
      return {
        content: [{ type: "text", text: `合計 ${summary.totalHours} 時間` }],
        // ❌ 宣言した形（totalHours / members）と違うキーで返している。
        // TypeScript では型で弾かれるため、Bad を再現するために意図的に型を潰しています。
        structuredContent: { total: summary.totalHours, rows: summary.members.length } as unknown as {
          totalHours: number;
          members: { memberId: string; totalHours: number }[];
        },
      };
    },
  );

  server.registerTool(
    "archive_project",
    {
      title: "プロジェクトのアーカイブ",
      description: "プロジェクトをアーカイブします。",
      inputSchema: { projectId: z.string() },
      // ❌ 破壊的操作なのに読み取り専用と申告している
      annotations: { readOnlyHint: true },
    },
    async ({ projectId }) => {
      if (findProject(projectId) === undefined) {
        // ❌ 失敗なのに isError を付けていない
        return { content: [{ type: "text", text: "エラー: 不明なプロジェクトです" }] };
      }
      const result = archiveProject(projectId);
      return { content: [{ type: "text", text: `アーカイブしました: ${result.projectId}` }] };
    },
  );

  server.registerTool(
    "exportReportCSV", // ❌ 他のツールは snake_case なのにここだけ camelCase
    {
      description: "CSV を返します。",
      inputSchema: { from: z.string(), to: z.string() },
      // ❌ 注釈なし → 既定値により「破壊的かもしれない」と解釈される
    },
    async ({ from, to }) => ({
      // ❌ CSV 全文をテキストで返している
      content: [{ type: "text", text: toCsv(buildReportRows(from, to)) }],
    }),
  );

  return server;
}
