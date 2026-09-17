/**
 * 問題1 の解答：list_projects を追加した 3 ツール構成のサーバー定義
 *
 * 本文の create-server.ts をコピーし、ファクトリ関数名と 1 ツールを足しただけです。
 * データ層（data.ts）には一切手を入れていません。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import {
  MAX_RANGE_DAYS,
  daysBetween,
  findMember,
  listMembers,
  projects,
  summarizeHours,
  workLogs,
  type HoursSummary,
  type Member,
  type Project,
} from "../data.js";

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const MEMBER_ID_PATTERN = /^m-\d{3}$/;

export function createDashboardServerQ1(): McpServer {
  const server = new McpServer({
    name: "team-dashboard",
    version: "0.2.0",
  });

  server.registerTool(
    "list_members",
    {
      title: "メンバー一覧",
      description:
        "チームに所属するメンバーの一覧（ID・氏名・チーム・週の稼働可能時間）を返します。" +
        "稼働時間を集計する前に、有効なメンバー ID を確認する用途で使ってください。",
      inputSchema: {
        team: z
          .enum(["platform", "data"])
          .describe("特定のチームだけに絞る場合に指定します。省略すると全員を返します。")
          .optional(),
      },
    },
    async ({ team }) => ({
      content: [{ type: "text", text: formatMembers(listMembers(team)) }],
    }),
  );

  server.registerTool(
    "list_projects",
    {
      title: "プロジェクト一覧",
      description:
        "プロジェクトの一覧（ID・名称）を返します。" +
        "memberId を指定すると、そのメンバーが稼働記録を持つプロジェクトだけに絞れます。" +
        "稼働時間をプロジェクト単位で見たいときに、対象プロジェクトを特定する用途で使ってください。",
      inputSchema: {
        memberId: z
          .string()
          .regex(MEMBER_ID_PATTERN, "m-001 のような形式で指定してください")
          .describe("指定したメンバーが稼働したプロジェクトだけに絞る場合に指定します。省略すると全件返します。")
          .optional(),
      },
    },
    async ({ memberId }) => {
      if (memberId !== undefined && findMember(memberId) === undefined) {
        return toolError(
          `メンバー ID ${memberId} は存在しません。list_members で有効な ID を確認してください。`,
        );
      }
      return {
        content: [{ type: "text", text: formatProjects(listProjects(memberId)) }],
      };
    },
  );

  server.registerTool(
    "summarize_hours",
    {
      title: "稼働時間の集計",
      description:
        "指定した期間の稼働時間をメンバー別に集計し、合計と内訳を返します。" +
        "期間は開始日・終了日の両方を含みます。" +
        `1 回で集計できるのは最長 ${MAX_RANGE_DAYS} 日です。`,
      inputSchema: {
        from: z
          .string()
          .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
          .describe("集計期間の開始日（YYYY-MM-DD、この日を含む）"),
        to: z
          .string()
          .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
          .describe("集計期間の終了日（YYYY-MM-DD、この日を含む）"),
        memberId: z
          .string()
          .regex(MEMBER_ID_PATTERN, "m-001 のような形式で指定してください")
          .describe("特定のメンバーだけを集計する場合に指定します。省略すると全員が対象です。")
          .optional(),
      },
    },
    async ({ from, to, memberId }) => {
      const span = daysBetween(from, to);
      if (Number.isNaN(span)) {
        return toolError("from / to には実在する日付を指定してください（例: 2026-08-03）。");
      }
      if (span <= 0) {
        return toolError(`from（${from}）は to（${to}）以前の日付を指定してください。`);
      }
      if (span > MAX_RANGE_DAYS) {
        return toolError(
          `集計できる期間は最長 ${MAX_RANGE_DAYS} 日です（指定された期間は ${span} 日）。` +
            "期間を分けて複数回呼び出してください。",
        );
      }
      if (memberId !== undefined && findMember(memberId) === undefined) {
        return toolError(
          `メンバー ID ${memberId} は存在しません。list_members で有効な ID を確認してください。`,
        );
      }
      return {
        content: [{ type: "text", text: formatSummary(summarizeHours({ from, to, memberId })) }],
      };
    },
  );

  return server;
}

/** memberId を指定した場合、そのメンバーの稼働記録があるプロジェクトだけを返す */
function listProjects(memberId?: string): Project[] {
  const sorted = [...projects].sort((a, b) => a.id.localeCompare(b.id));
  if (memberId === undefined) {
    return sorted;
  }
  const worked = new Set(
    workLogs.filter((log) => log.memberId === memberId).map((log) => log.projectId),
  );
  return sorted.filter((project) => worked.has(project.id));
}

function toolError(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

function formatProjects(found: Project[]): string {
  if (found.length === 0) {
    return "該当するプロジェクトはありません。";
  }
  const lines = found.map((project) => `- ${project.id} ${project.name}`);
  return [`プロジェクト ${found.length} 件`, ...lines].join("\n");
}

function formatMembers(found: Member[]): string {
  if (found.length === 0) {
    return "該当するメンバーはいません。";
  }
  const lines = found.map(
    (member) =>
      `- ${member.id} ${member.name}（${member.team} / 週 ${member.weeklyCapacityHours} 時間）`,
  );
  return [`メンバー ${found.length} 名`, ...lines].join("\n");
}

function formatSummary(summary: HoursSummary): string {
  const header = `${summary.from} 〜 ${summary.to} の稼働時間: 合計 ${summary.totalHours} 時間 / 対象 ${summary.members.length} 名`;
  if (summary.members.length === 0) {
    return `${header}\n対象期間に稼働記録はありません。`;
  }
  const lines = summary.members.map(
    (row) =>
      `- ${row.name}（${row.memberId} / ${row.team}）: ${row.totalHours} 時間 / ${row.workedDays} 日`,
  );
  return [header, ...lines].join("\n");
}
