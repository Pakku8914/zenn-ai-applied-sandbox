/**
 * 横断復習1 の共通題材 ― チーム稼働ダッシュボード（日次ビュー）
 *
 * セッション3 の create-server.ts と同じ構造です。トランスポートへの接続は
 * このファイルでは行いません（server.ts の責務）。
 *
 * データ層をこのファイルに同居させているのは、復習章の題材を配りやすくするための
 * 例外です。本来はセッション3 のように data.ts へ分けます。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export type Member = {
  readonly id: string;
  readonly name: string;
  readonly team: "platform" | "data";
};

export type WorkLog = {
  readonly memberId: string;
  /** YYYY-MM-DD。辞書順の比較がそのまま時系列の比較になる */
  readonly date: string;
  readonly hours: number;
};

/** 1 回で調べられる期間の上限（日数）。処理量の上限はリソース枯渇対策（詳細はセッション15） */
export const MAX_RANGE_DAYS = 92;

export const members: readonly Member[] = [
  { id: "m-001", name: "佐藤 花子", team: "platform" },
  { id: "m-002", name: "鈴木 一郎", team: "platform" },
  { id: "m-003", name: "田中 美咲", team: "data" },
  { id: "m-004", name: "高橋 健", team: "data" },
];

export const workLogs: readonly WorkLog[] = [
  { memberId: "m-001", date: "2026-08-03", hours: 5 },
  { memberId: "m-002", date: "2026-08-03", hours: 7.5 },
  { memberId: "m-003", date: "2026-08-03", hours: 6 },
  { memberId: "m-001", date: "2026-08-04", hours: 3 },
  { memberId: "m-002", date: "2026-08-04", hours: 6 },
  { memberId: "m-004", date: "2026-08-04", hours: 8 },
  { memberId: "m-001", date: "2026-08-05", hours: 4 },
  { memberId: "m-003", date: "2026-08-05", hours: 5.5 },
  { memberId: "m-004", date: "2026-08-05", hours: 3 },
  { memberId: "m-002", date: "2026-08-06", hours: 2 },
  { memberId: "m-004", date: "2026-08-07", hours: 6 },
];

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function findMember(memberId: string): Member | undefined {
  return members.find((member) => member.id === memberId);
}

/** 両端を含む日数。日付として解釈できない場合は NaN を返す（UTC 固定で計算する） */
export function daysBetween(from: string, to: string): number {
  const fromMs = Date.parse(`${from}T00:00:00Z`);
  const toMs = Date.parse(`${to}T00:00:00Z`);
  if (Number.isNaN(fromMs) || Number.isNaN(toMs)) {
    return Number.NaN;
  }
  return Math.floor((toMs - fromMs) / 86_400_000) + 1;
}

/** 12 を "12"、18.5 を "18.5" と表示する（小数第 1 位に丸める） */
export function formatHours(hours: number): string {
  return String(Math.round(hours * 10) / 10);
}

export type DayRow = { memberId: string; name: string; team: string; hours: number };

/** 指定日の稼働をメンバー別に集計する。team を渡すとそのチームだけに絞る */
export function rowsOfDay(date: string, team?: string): DayRow[] {
  const buckets = new Map<string, number>();
  for (const log of workLogs) {
    if (log.date !== date) continue;
    const member = findMember(log.memberId);
    if (member === undefined) continue;
    if (team !== undefined && member.team !== team) continue;
    buckets.set(log.memberId, (buckets.get(log.memberId) ?? 0) + log.hours);
  }

  const rows: DayRow[] = [];
  for (const [memberId, hours] of buckets) {
    const member = findMember(memberId);
    rows.push({
      memberId,
      name: member?.name ?? "(不明)",
      team: member?.team ?? "(不明)",
      hours,
    });
  }
  return rows.sort((a, b) => a.memberId.localeCompare(b.memberId));
}

/** ツール実行の失敗を表す戻り値（JSON-RPC のエラーではない） */
function toolError(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

export function createDailyServer(): McpServer {
  const server = new McpServer({ name: "team-dashboard-daily", version: "0.1.0" });

  server.registerTool(
    "daily_hours",
    {
      title: "日次の稼働時間",
      description:
        "指定した 1 日の稼働時間を、メンバー別の内訳付きで返します。" +
        "team を指定するとそのチームだけに絞れます。" +
        "複数日をまたぐ調査には busiest_day を使ってください。",
      inputSchema: {
        date: z
          .string()
          .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
          .describe("集計する日（YYYY-MM-DD）"),
        team: z
          .enum(["platform", "data"])
          .describe("特定のチームだけに絞る場合に指定します。省略すると全チームが対象です。")
          .optional(),
      },
    },
    async ({ date, team }) => {
      // 形式は Zod が保証済み。ここでは「形式は正しいが実在しない日付」を弾く
      if (Number.isNaN(daysBetween(date, date))) {
        return toolError("date には実在する日付を指定してください（例: 2026-08-04）。");
      }

      const rows = rowsOfDay(date, team);
      const total = rows.reduce((sum, row) => sum + row.hours, 0);
      const header = `${date} の稼働時間（${team ?? "全チーム"}）: 合計 ${formatHours(total)} 時間 / ${rows.length} 名`;

      if (rows.length === 0) {
        // 「0 件」は失敗ではない。正常な結果として返す
        return { content: [{ type: "text", text: `${header}\nこの日の稼働記録はありません。` }] };
      }

      const lines = rows.map(
        (row) => `- ${row.name}（${row.memberId} / ${row.team}）: ${formatHours(row.hours)} 時間`,
      );
      return { content: [{ type: "text", text: [header, ...lines].join("\n") }] };
    },
  );

  server.registerTool(
    "busiest_day",
    {
      title: "最も忙しかった日",
      description:
        "指定した期間のうち、チーム全体の稼働時間が最も多かった 1 日を返します。" +
        "同じ時間の日が複数ある場合は最も早い日を返します。" +
        `1 回で調べられるのは最長 ${MAX_RANGE_DAYS} 日です。`,
      inputSchema: {
        from: z
          .string()
          .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
          .describe("調査期間の開始日（YYYY-MM-DD、この日を含む）"),
        to: z
          .string()
          .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
          .describe("調査期間の終了日（YYYY-MM-DD、この日を含む）"),
      },
    },
    async ({ from, to }) => {
      const span = daysBetween(from, to);
      if (Number.isNaN(span)) {
        return toolError("from / to には実在する日付を指定してください（例: 2026-08-03）。");
      }
      if (span <= 0) {
        return toolError(`from（${from}）は to（${to}）以前の日付を指定してください。`);
      }
      if (span > MAX_RANGE_DAYS) {
        return toolError(
          `調べられる期間は最長 ${MAX_RANGE_DAYS} 日です（指定された期間は ${span} 日）。` +
            "期間を分けて複数回呼び出してください。",
        );
      }

      const totals = new Map<string, number>();
      for (const log of workLogs) {
        if (log.date < from || log.date > to) continue;
        totals.set(log.date, (totals.get(log.date) ?? 0) + log.hours);
      }
      if (totals.size === 0) {
        // 「最も多い日」を返す契約なので、返す値が無い＝ツール実行の失敗
        return toolError(`${from} 〜 ${to} に稼働記録がありません。期間を広げて再試行してください。`);
      }

      let bestDate = "";
      let bestHours = -1;
      for (const date of [...totals.keys()].sort()) {
        const hours = totals.get(date) ?? 0;
        if (hours > bestHours) {
          bestDate = date;
          bestHours = hours;
        }
      }

      const count = rowsOfDay(bestDate).length;
      return {
        content: [
          {
            type: "text",
            text: `${from} 〜 ${to} で最も稼働時間が多い日: ${bestDate}（${formatHours(bestHours)} 時間 / ${count} 名）`,
          },
        ],
      };
    },
  );

  return server;
}
