/**
 * 問題1 の解答：list_projects を追加する
 *
 * 本文の create-server.ts を丸ごとコピーしてもよいのですが、
 * ファクトリ関数を再利用すればコードの重複はゼロになります。
 * 「サーバー定義をファクトリ関数として公開しておく」設計の副産物です。
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { createDashboardServer } from "../create-server.js";
import { isArchived, listActiveProjects, projects, type Project } from "../data.js";

export function createDashboardServerQ1(): McpServer {
  const server = createDashboardServer();
  registerListProjects(server);
  return server;
}

function registerListProjects(server: McpServer): void {
  server.registerTool(
    "list_projects",
    {
      title: "プロジェクト一覧",
      description:
        "プロジェクトの一覧（ID・名称・アーカイブ済みかどうか）を返します。" +
        "archive_project や export_report を呼ぶ前に、有効なプロジェクト ID を確認する用途で使ってください。" +
        "既定ではアーカイブ済みのプロジェクトを含めません。",
      inputSchema: {
        includeArchived: z
          .boolean()
          .default(false)
          .describe("true にするとアーカイブ済みのプロジェクトも含めます。既定は false。"),
      },
      outputSchema: {
        count: z.number().int().describe("返したプロジェクトの件数"),
        projects: z
          .array(
            z.object({
              projectId: z.string().describe("プロジェクト ID（archive_project に渡せます）"),
              name: z.string().describe("プロジェクト名"),
              archived: z.boolean().describe("アーカイブ済みかどうか"),
            }),
          )
          .describe("プロジェクトの一覧（プロジェクト ID の昇順）"),
      },
      // 読み取り専用ツールに書くのはこの 2 つだけ
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ includeArchived }) => {
      const target: Project[] = includeArchived
        ? [...projects].sort((a, b) => a.id.localeCompare(b.id))
        : listActiveProjects();

      const rows = target.map((project) => ({
        projectId: project.id,
        name: project.name,
        archived: isArchived(project.id),
      }));

      const heading = includeArchived
        ? `プロジェクト ${rows.length} 件（アーカイブ済みを含む）`
        : `アクティブなプロジェクト ${rows.length} 件`;
      const lines = rows.map(
        (row) => `- ${row.projectId} ${row.name}${row.archived ? "（アーカイブ済み）" : ""}`,
      );

      return {
        content: [{ type: "text", text: [heading, ...lines].join("\n") }],
        structuredContent: { count: rows.length, projects: rows },
      };
    },
  );
}
