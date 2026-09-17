/**
 * 横断復習1 問題6 ― Python の member_days を TypeScript へ移植する
 *
 * dashboard.ts は変更せず、createDailyServer() が返したサーバーに 3 本目を足します。
 * 「サーバー定義」と「トランスポート接続」を分けてあるからこそ、この足し方ができます。
 *
 *   docker compose exec node npx mcp-inspector --cli npx tsx src/review01/q6-server.ts --method tools/list
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { createDailyServer, findMember, formatHours, workLogs } from "./dashboard.js";

/** Python 版の MemberIdStr（Field(pattern=...) 付きの型）に対応 */
const MEMBER_ID_PATTERN = /^m-\d{3}$/;

/** Python 版の MonthStr に対応 */
const MONTH_PATTERN = /^\d{4}-\d{2}$/;

const server = createDailyServer();

server.registerTool(
  "member_days",
  {
    title: "メンバーの稼働日数",
    description:
      "指定したメンバーが稼働した日数と、日付ごとの内訳を返します。" +
      "month を指定するとその月だけに絞れます。" +
      "チーム全体の集計には daily_hours を使ってください。",
    inputSchema: {
      memberId: z
        .string()
        .regex(MEMBER_ID_PATTERN, "m-001 のような形式で指定してください")
        .describe("対象のメンバー ID（m-001 のような形式）"),
      month: z
        .string()
        .regex(MONTH_PATTERN, "YYYY-MM 形式で指定してください")
        .describe("絞り込む月（YYYY-MM）。省略すると全期間が対象です。")
        .optional(),
    },
  },
  async ({ memberId, month }) => {
    // 形式は Zod が保証済み。ここでは「形式は正しいが存在しない ID」を弾く
    const member = findMember(memberId);
    if (member === undefined) {
      return {
        content: [
          {
            type: "text",
            text:
              `メンバー ID ${memberId} は存在しません。` +
              "daily_hours の結果に出ている ID を確認してください。",
          },
        ],
        isError: true,
      };
    }

    const logs = workLogs
      .filter((log) => log.memberId === memberId)
      .filter((log) => month === undefined || log.date.startsWith(month))
      .sort((a, b) => a.date.localeCompare(b.date));

    const hoursByDate = new Map<string, number>();
    for (const log of logs) {
      hoursByDate.set(log.date, (hoursByDate.get(log.date) ?? 0) + log.hours);
    }
    const total = logs.reduce((sum, log) => sum + log.hours, 0);

    const scope = month === undefined ? "" : ` ${month} の`;
    const header =
      `${member.id} ${member.name}（${member.team}）の${scope}稼働日数: ` +
      `${hoursByDate.size} 日 / 合計 ${formatHours(total)} 時間`;

    if (hoursByDate.size === 0) {
      // 「記録が無い」は失敗ではない。正常な結果として返す
      return { content: [{ type: "text", text: `${header}\n対象期間に稼働記録はありません。` }] };
    }

    const lines = [...hoursByDate.entries()].map(
      ([date, hours]) => `- ${date}: ${formatHours(hours)} 時間`,
    );
    return { content: [{ type: "text", text: [header, ...lines].join("\n") }] };
  },
);

await server.connect(new StdioServerTransport());

console.error("[team-dashboard-daily] stdio でリクエストを待機しています（member_days を追加）");
