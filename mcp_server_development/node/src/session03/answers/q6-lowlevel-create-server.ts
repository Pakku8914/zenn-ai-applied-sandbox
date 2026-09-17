/**
 * 問題6 の解答：低水準 Server クラスだけで 2 ツールを実装する
 *
 * McpServer と zod を使いません。その結果、次のすべてが自分の仕事になります。
 *   - ケイパビリティの宣言
 *   - tools/list のレスポンス（JSON Schema を手書き）
 *   - tools/call のディスパッチ
 *   - 引数の型・必須・形式・列挙の検証
 *   - 未知のツール名への応答
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
  type CallToolResult,
  type ListToolsResult,
} from "@modelcontextprotocol/sdk/types.js";

import {
  MAX_RANGE_DAYS,
  daysBetween,
  findMember,
  listMembers,
  summarizeHours,
  type HoursSummary,
  type Member,
} from "../data.js";

const TEAMS = ["platform", "data"] as const;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const MEMBER_ID_PATTERN = /^m-\d{3}$/;

export function createLowLevelServerQ6(): Server {
  // ① ケイパビリティを手で宣言する
  const server = new Server(
    { name: "team-dashboard-lowlevel", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  // ② tools/list のレスポンスを手で組み立てる
  server.setRequestHandler(
    ListToolsRequestSchema,
    async (): Promise<ListToolsResult> => ({
      tools: [
        {
          name: "list_members",
          title: "メンバー一覧",
          description:
            "チームに所属するメンバーの一覧（ID・氏名・チーム・週の稼働可能時間）を返します。" +
            "稼働時間を集計する前に、有効なメンバー ID を確認する用途で使ってください。",
          inputSchema: {
            type: "object",
            properties: {
              team: {
                type: "string",
                enum: [...TEAMS],
                description: "特定のチームだけに絞る場合に指定します。省略すると全員を返します。",
              },
            },
          },
        },
        {
          name: "summarize_hours",
          title: "稼働時間の集計",
          description:
            "指定した期間の稼働時間をメンバー別に集計し、合計と内訳を返します。" +
            "期間は開始日・終了日の両方を含みます。" +
            `1 回で集計できるのは最長 ${MAX_RANGE_DAYS} 日です。`,
          inputSchema: {
            type: "object",
            properties: {
              from: {
                type: "string",
                pattern: DATE_PATTERN.source,
                description: "集計期間の開始日（YYYY-MM-DD、この日を含む）",
              },
              to: {
                type: "string",
                pattern: DATE_PATTERN.source,
                description: "集計期間の終了日（YYYY-MM-DD、この日を含む）",
              },
              memberId: {
                type: "string",
                pattern: MEMBER_ID_PATTERN.source,
                description: "特定のメンバーだけを集計する場合に指定します。省略すると全員が対象です。",
              },
            },
            required: ["from", "to"],
          },
        },
      ],
    }),
  );

  // ③ tools/call のディスパッチと引数検証
  server.setRequestHandler(
    CallToolRequestSchema,
    async (request): Promise<CallToolResult> => {
      const args = request.params.arguments ?? {};

      switch (request.params.name) {
        case "list_members": {
          const team = optionalEnum(args, "team", TEAMS);
          return { content: [{ type: "text", text: formatMembers(listMembers(team)) }] };
        }
        case "summarize_hours": {
          const from = requiredString(args, "from", DATE_PATTERN);
          const to = requiredString(args, "to", DATE_PATTERN);
          const memberId = optionalString(args, "memberId", MEMBER_ID_PATTERN);

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
        }
        default:
          // ④ 未知のツール名への応答も自分の責任
          throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${request.params.name}`);
      }
    },
  );

  return server;
}

/** 必須の文字列引数を検証して取り出す */
function requiredString(args: Record<string, unknown>, key: string, pattern: RegExp): string {
  const value = args[key];
  if (value === undefined || value === null) {
    throw new McpError(ErrorCode.InvalidParams, `${key} は必須です`);
  }
  if (typeof value !== "string") {
    throw new McpError(ErrorCode.InvalidParams, `${key} は文字列で指定してください`);
  }
  if (!pattern.test(value)) {
    throw new McpError(
      ErrorCode.InvalidParams,
      `${key} の形式が不正です（期待する形式: ${pattern.source}）`,
    );
  }
  return value;
}

/** 任意の文字列引数を検証して取り出す */
function optionalString(
  args: Record<string, unknown>,
  key: string,
  pattern: RegExp,
): string | undefined {
  if (args[key] === undefined || args[key] === null) {
    return undefined;
  }
  return requiredString(args, key, pattern);
}

/** 任意の列挙引数を検証して取り出す */
function optionalEnum<T extends readonly string[]>(
  args: Record<string, unknown>,
  key: string,
  allowed: T,
): T[number] | undefined {
  const value = args[key];
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== "string") {
    throw new McpError(ErrorCode.InvalidParams, `${key} は文字列で指定してください`);
  }
  if (!allowed.includes(value)) {
    throw new McpError(
      ErrorCode.InvalidParams,
      `${key} は ${allowed.join(" / ")} のいずれかを指定してください`,
    );
  }
  // includes による絞り込みは型に伝わらないため、検証済みであることを明示する
  return value as T[number];
}

function toolError(message: string): CallToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
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
