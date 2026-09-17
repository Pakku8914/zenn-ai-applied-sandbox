/**
 * 問題4 の解答：summarize_hours に groupBy（member / project）を追加
 *
 * 問題1 の 3 ツール構成に、集計軸の切り替えを足しています。
 * データ層（data.ts）は変更せず、プロジェクト別の集計はこのファイルに実装します。
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

/** 集計軸。スキーマとハンドラでこの 1 か所を共有する */
const GROUP_BY = ["member", "project"] as const;
type GroupBy = (typeof GROUP_BY)[number];

export function createDashboardServerQ4(): McpServer {
  const server = new McpServer({
    name: "team-dashboard",
    version: "0.3.0",
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
        "memberId を指定すると、そのメンバーが稼働記録を持つプロジェクトだけに絞れます。",
      inputSchema: {
        memberId: z
          .string()
          .regex(MEMBER_ID_PATTERN, "m-001 のような形式で指定してください")
          .describe("指定したメンバーが稼働したプロジェクトだけに絞る場合に指定します。")
          .optional(),
      },
    },
    async ({ memberId }) => {
      if (memberId !== undefined && findMember(memberId) === undefined) {
        return toolError(
          `メンバー ID ${memberId} は存在しません。list_members で有効な ID を確認してください。`,
        );
      }
      return { content: [{ type: "text", text: formatProjects(listProjects(memberId)) }] };
    },
  );

  server.registerTool(
    "summarize_hours",
    {
      title: "稼働時間の集計",
      description:
        "指定した期間の稼働時間を集計し、合計と内訳を返します。" +
        "期間は開始日・終了日の両方を含みます。" +
        "groupBy でメンバー別（既定）とプロジェクト別を切り替えられます。" +
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
        groupBy: z
          .enum(GROUP_BY)
          .describe(
            "集計軸。member はメンバー別、project はプロジェクト別に集計します。省略すると member として扱います。",
          )
          .optional(),
      },
    },
    async ({ from, to, memberId, groupBy }) => {
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

      // 既定値はスキーマではなくサーバー側で決める
      const mode: GroupBy = groupBy ?? "member";

      switch (mode) {
        case "member": {
          const summary = summarizeHours({ from, to, memberId });
          return { content: [{ type: "text", text: formatSummary(summary) }] };
        }
        case "project": {
          const summary = summarizeByProject({ from, to, memberId });
          return { content: [{ type: "text", text: formatProjectSummary(summary) }] };
        }
        default: {
          // GROUP_BY に値を足してここを書き忘れると、この行がコンパイルエラーになる
          const unreachable: never = mode;
          throw new Error(`未対応の groupBy: ${String(unreachable)}`);
        }
      }
    },
  );

  return server;
}

type ProjectHours = {
  projectId: string;
  name: string;
  totalHours: number;
  memberCount: number;
};

type ProjectSummary = {
  from: string;
  to: string;
  totalHours: number;
  projects: ProjectHours[];
};

/** 期間内の稼働時間をプロジェクト別に集計する */
function summarizeByProject(params: { from: string; to: string; memberId?: string }): ProjectSummary {
  const { from, to, memberId } = params;

  const targets = workLogs.filter(
    (log) =>
      log.date >= from &&
      log.date <= to &&
      (memberId === undefined || log.memberId === memberId),
  );

  const buckets = new Map<string, { hours: number; members: Set<string> }>();
  for (const log of targets) {
    const bucket = buckets.get(log.projectId) ?? { hours: 0, members: new Set<string>() };
    bucket.hours += log.hours;
    bucket.members.add(log.memberId);
    buckets.set(log.projectId, bucket);
  }

  const rows: ProjectHours[] = [];
  for (const [id, bucket] of buckets) {
    rows.push({
      projectId: id,
      name: projects.find((project) => project.id === id)?.name ?? "(不明なプロジェクト)",
      totalHours: roundHours(bucket.hours),
      memberCount: bucket.members.size,
    });
  }
  rows.sort((a, b) => a.projectId.localeCompare(b.projectId));

  return {
    from,
    to,
    totalHours: roundHours(rows.reduce((sum, row) => sum + row.totalHours, 0)),
    projects: rows,
  };
}

function roundHours(hours: number): number {
  return Math.round(hours * 10) / 10;
}

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

function formatProjectSummary(summary: ProjectSummary): string {
  const header = `${summary.from} 〜 ${summary.to} の稼働時間: 合計 ${summary.totalHours} 時間 / 対象 ${summary.projects.length} プロジェクト`;
  if (summary.projects.length === 0) {
    return `${header}\n対象期間に稼働記録はありません。`;
  }
  const lines = summary.projects.map(
    (row) => `- ${row.name}（${row.projectId}）: ${row.totalHours} 時間 / ${row.memberCount} 名`,
  );
  return [header, ...lines].join("\n");
}

function formatProjects(found: Project[]): string {
  if (found.length === 0) {
    return "該当するプロジェクトはありません。";
  }
  return [`プロジェクト ${found.length} 件`, ...found.map((p) => `- ${p.id} ${p.name}`)].join("\n");
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
