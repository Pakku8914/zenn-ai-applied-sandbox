/**
 * 問題7 の解答：検査用の Bad サーバー
 *
 * Bad 実装（注釈が嘘）に、状態を読み出せる読み取り専用ツール list_projects を足します。
 * 「検査には観測手段が必要」という、テスト設計の一般則がここに出ています。
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { createBadDashboardServer } from "../bad-create-server.js";
import { isArchived, projects } from "../data.js";

export function createAuditableBadServer(): McpServer {
  const server = createBadDashboardServer();

  server.registerTool(
    "list_projects",
    {
      title: "プロジェクト一覧",
      description: "プロジェクトの一覧とアーカイブ状態を返します（検査用の観測手段）。",
      inputSchema: {
        includeArchived: z.boolean().default(false).describe("アーカイブ済みも含めるか"),
      },
      outputSchema: {
        count: z.number().int(),
        projects: z.array(
          z.object({ projectId: z.string(), name: z.string(), archived: z.boolean() }),
        ),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ includeArchived }) => {
      const rows = [...projects]
        .sort((a, b) => a.id.localeCompare(b.id))
        .filter((project) => includeArchived || !isArchived(project.id))
        .map((project) => ({
          projectId: project.id,
          name: project.name,
          archived: isArchived(project.id),
        }));
      return {
        content: [{ type: "text", text: `プロジェクト ${rows.length} 件` }],
        structuredContent: { count: rows.length, projects: rows },
      };
    },
  );

  return server;
}
