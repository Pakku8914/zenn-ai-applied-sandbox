/**
 * 問題3 の解答：Bad 実装の archive_project を修正する
 *
 * 修正した点
 *   ① 注釈を 4 つすべて明示（破壊的・冪等・閉じた世界）
 *   ② reason を必須にし、長さを制限
 *   ③ projectId に形式と説明を付与
 *   ④ 失敗を isError: true で表明し、回復方法（有効な ID）を本文に含める
 *   ⑤ outputSchema を宣言し、成功時に structuredContent を返す
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { archiveProject, findProject, listActiveProjects } from "../data.js";

export function createFixedArchiveServer(): McpServer {
  const server = new McpServer({ name: "team-dashboard-q3", version: "0.2.0" });

  server.registerTool(
    "archive_project",
    {
      title: "プロジェクトのアーカイブ",
      description:
        "指定したプロジェクトをアーカイブし、以後アクティブなプロジェクト一覧に出さないようにします。" +
        "稼働記録そのものは削除しません。すでにアーカイブ済みの場合も成功として扱います。" +
        "元に戻すツールは用意していないため、ユーザーから明示的に依頼された場合だけ呼び出してください。",
      inputSchema: {
        projectId: z
          .string()
          .regex(/^p-[a-z-]{2,32}$/, "p-portal のような形式で指定してください")
          .describe("アーカイブするプロジェクトの ID（例: p-search）"),
        reason: z
          .string()
          .min(3)
          .max(200)
          .describe("アーカイブする理由。監査ログに記録されます（3〜200 文字）"),
      },
      outputSchema: {
        projectId: z.string(),
        name: z.string().describe("プロジェクト名"),
        alreadyArchived: z.boolean().describe("呼び出し前からアーカイブ済みだったか"),
        archivedAt: z.string().describe("アーカイブした日時（ISO 8601）"),
        affectedWorkLogs: z.number().int().describe("紐づく稼働記録の件数（削除はしません）"),
        affectedHours: z.number().describe("紐づく稼働記録の合計時間"),
        remainingActiveProjects: z.array(z.string()).describe("残っているプロジェクトの ID"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async ({ projectId, reason }) => {
      if (findProject(projectId) === undefined) {
        // 何が悪いか（存在しない）＋ どう直すか（有効な ID）を返す。
        // 内部例外の文字列やパスは一切含めない
        return {
          content: [
            {
              type: "text",
              text:
                `プロジェクト ID ${projectId} は存在しません。` +
                `有効な ID: ${listActiveProjects()
                  .map((project) => project.id)
                  .join(", ")}`,
            },
          ],
          isError: true,
        };
      }

      console.error(`[audit] archive_project projectId=${projectId} reason=${reason}`);
      const result = archiveProject(projectId);

      return {
        content: [
          {
            type: "text",
            text:
              (result.alreadyArchived
                ? `${result.name}（${result.projectId}）はすでにアーカイブ済みです。`
                : `${result.name}（${result.projectId}）をアーカイブしました。`) +
              `紐づく稼働記録 ${result.affectedWorkLogs} 件は削除されず残ります。`,
          },
        ],
        structuredContent: { ...result },
      };
    },
  );

  return server;
}
