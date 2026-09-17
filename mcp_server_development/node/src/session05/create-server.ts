/**
 * チーム稼働ダッシュボード ― サーバー定義（セッション5 版）
 *
 * セッション3 との違いは 4 点です。
 *   ① 全ツールに outputSchema と structuredContent を付けた
 *   ② 全ツールに注釈（annotations）を付けた
 *   ③ 破壊的操作 archive_project を追加した
 *   ④ CSV を resource_link で返す export_report を追加した
 *
 * トランスポートへの接続はここでは行いません（server.ts の責務）。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import {
  MAX_INLINE_BYTES,
  MAX_RANGE_DAYS,
  archiveProject,
  buildReportRows,
  byteSizeOf,
  daysBetween,
  findMember,
  findProject,
  listActiveProjects,
  listMembers,
  sumHours,
  summarizeHours,
  toCsv,
  type HoursSummary,
  type Member,
} from "./data.js";

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const MEMBER_ID_PATTERN = /^m-\d{3}$/;
const PROJECT_ID_PATTERN = /^p-[a-z-]{2,32}$/;

export function createDashboardServer(): McpServer {
  const server = new McpServer({
    name: "team-dashboard",
    // ツールが増えたのでマイナーバージョンを上げています（配布時の作法はセッション14）
    version: "0.2.0",
  });

  // ------------------------------------------------------------------
  // 1. list_members ― 読み取り専用 + 構造化出力
  // ------------------------------------------------------------------
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
      // 出力の形を宣言する。キー名は他のツールと揃える（id ではなく memberId）
      outputSchema: {
        count: z.number().int().describe("返したメンバーの件数"),
        members: z
          .array(
            z.object({
              memberId: z.string().describe("メンバー ID（summarize_hours の memberId に渡せます）"),
              name: z.string().describe("氏名"),
              team: z.string().describe("所属チーム（platform / data）"),
              weeklyCapacityHours: z.number().describe("週の稼働可能時間"),
            }),
          )
          .describe("メンバーの一覧（メンバー ID の昇順）"),
      },
      // 読み取り専用ツールに書くのはこの 2 つだけでよい（理由は 5 節）
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ team }) => {
      const found = listMembers(team);
      const rows = found.map((member) => ({
        memberId: member.id,
        name: member.name,
        team: member.team,
        weeklyCapacityHours: member.weeklyCapacityHours,
      }));
      return {
        // モデルと人間が読む表現
        content: [{ type: "text", text: formatMembers(found) }],
        // プログラムが読む表現（outputSchema に一致していないと検証で落ちる）
        structuredContent: { count: rows.length, members: rows },
      };
    },
  );

  // ------------------------------------------------------------------
  // 2. summarize_hours ― 読み取り専用 + 構造化出力 + 業務エラー
  // ------------------------------------------------------------------
  server.registerTool(
    "summarize_hours",
    {
      title: "稼働時間の集計",
      description:
        "指定した期間の稼働時間をメンバー別に集計し、合計と内訳を返します。" +
        "期間は開始日・終了日の両方を含みます。" +
        `1 回で集計できるのは最長 ${MAX_RANGE_DAYS} 日です。` +
        "結果は構造化出力（structuredContent）にも入るので、合計値だけを使う場合はそちらを参照してください。",
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
      outputSchema: {
        from: z.string().describe("集計期間の開始日"),
        to: z.string().describe("集計期間の終了日"),
        totalHours: z.number().describe("期間内の合計稼働時間"),
        memberCount: z.number().int().describe("稼働記録があったメンバーの人数"),
        members: z
          .array(
            z.object({
              memberId: z.string(),
              name: z.string(),
              team: z.string(),
              totalHours: z.number().describe("そのメンバーの合計稼働時間"),
              workedDays: z.number().int().describe("稼働記録があった日数"),
            }),
          )
          .describe("メンバー別の内訳（メンバー ID の昇順）"),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
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

      const summary = summarizeHours({ from, to, memberId });
      return {
        content: [{ type: "text", text: formatSummary(summary) }],
        structuredContent: {
          from: summary.from,
          to: summary.to,
          totalHours: summary.totalHours,
          memberCount: summary.members.length,
          members: summary.members,
        },
      };
    },
  );

  registerArchiveProject(server);
  registerExportReport(server);

  return server;
}

/**
 * 破壊的操作を登録する。
 *
 * 破壊的操作を作るときのチェックリスト（本書の推奨）
 *   ① 注釈を 4 つすべて明示する
 *   ② 監査用の理由（reason）を必須引数にする
 *   ③ 影響範囲を結果に含める（何件に影響したのか）
 *   ④ 冪等にする（2 回呼ばれても壊れない）
 *   ⑤ 破壊の範囲を最小にする（ここでは稼働記録を削除しない）
 */
function registerArchiveProject(server: McpServer): void {
  server.registerTool(
    "archive_project",
    {
      title: "プロジェクトのアーカイブ",
      description:
        "指定したプロジェクトをアーカイブし、以後アクティブなプロジェクト一覧に出さないようにします。" +
        "稼働記録そのものは削除しません。" +
        "すでにアーカイブ済みの場合も成功として扱い、同じ結果を返します。" +
        "元に戻すツールは用意していないため、ユーザーから明示的に依頼された場合だけ呼び出してください。",
      inputSchema: {
        projectId: z
          .string()
          .regex(PROJECT_ID_PATTERN, "p-portal のような形式で指定してください")
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
        affectedWorkLogs: z
          .number()
          .int()
          .describe("このプロジェクトに紐づく稼働記録の件数（削除はしません）"),
        affectedHours: z.number().describe("紐づく稼働記録の合計時間"),
        remainingActiveProjects: z
          .array(z.string())
          .describe("アーカイブされずに残っているプロジェクトの ID"),
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
        // AI が自力で回復できる情報を返す：何が悪いか + どう直すか
        return toolError(
          `プロジェクト ID ${projectId} は存在しません。` +
            `有効な ID: ${listActiveProjects()
              .map((project) => project.id)
              .join(", ")}`,
        );
      }

      // 監査ログは stderr へ。stdout は JSON-RPC の通信路なので絶対に使わない
      // （監査ログの設計はセッション15 で扱います）
      console.error(`[audit] archive_project projectId=${projectId} reason=${reason}`);

      const result = archiveProject(projectId);
      const head = result.alreadyArchived
        ? `${result.name}（${result.projectId}）はすでにアーカイブ済みです。`
        : `${result.name}（${result.projectId}）をアーカイブしました。`;

      return {
        content: [
          {
            type: "text",
            text:
              `${head} 紐づく稼働記録 ${result.affectedWorkLogs} 件（${result.affectedHours} 時間）は削除されず残ります。` +
              `アクティブなプロジェクト: ${result.remainingActiveProjects.join(", ")}`,
          },
        ],
        structuredContent: { ...result },
      };
    },
  );
}

/**
 * ツール実行の失敗を表す戻り値。
 *
 * outputSchema を宣言しているツールでも、isError: true のときは structuredContent を
 * 省略できます（仕様で「エラー時は構造化結果を返さなくてよい」と決まっているため）。
 * SDK もこのときは検証をスキップします。
 *
 * 返す文章には次の 3 つを入れます（詳しい設計はセッション11）。
 *   ① 何が悪いのか   ② どう直せばよいのか   ③ 再試行してよいのか
 */
function toolError(message: string) {
  return {
    content: [{ type: "text" as const, text: message }],
    isError: true,
  };
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

/**
 * 稼働レポートを CSV で書き出すツール。
 *
 * 既定では本文を返さず resource_link（参照）だけを返します。
 * inline: true を指定されたときだけ本文を埋め込み、しかも上限を超える場合は
 * サーバーの判断で参照に切り替えます（呼び出し側の指定より、サーバーの上限が優先）。
 */
function registerExportReport(server: McpServer): void {
  server.registerTool(
    "export_report",
    {
      title: "稼働レポートの書き出し（CSV）",
      description:
        "指定期間の稼働記録を CSV に書き出し、リソースへの参照（resource_link）を返します。" +
        "CSV の本文はレスポンスに含めません。中身が必要な場合は返された URI を読み取ってください。" +
        `inline に true を指定すると本文を埋め込みますが、${MAX_INLINE_BYTES} バイトを超える場合は自動的に参照に切り替わります。` +
        `1 回で書き出せるのは最長 ${MAX_RANGE_DAYS} 日です。`,
      inputSchema: {
        from: z
          .string()
          .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
          .describe("書き出す期間の開始日（YYYY-MM-DD、この日を含む）"),
        to: z
          .string()
          .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
          .describe("書き出す期間の終了日（YYYY-MM-DD、この日を含む）"),
        inline: z
          .boolean()
          .default(false)
          .describe(
            `true にすると CSV 本文をレスポンスに埋め込みます（${MAX_INLINE_BYTES} バイトまで）。既定は false（参照のみ）。`,
          ),
      },
      outputSchema: {
        uri: z.string().describe("生成した CSV リソースの URI"),
        rows: z.number().int().describe("CSV のデータ行数（ヘッダー行を除く）"),
        totalHours: z.number().describe("期間内の合計稼働時間"),
        byteSize: z.number().int().describe("CSV 本文のバイト数（UTF-8）"),
        delivery: z
          .string()
          .describe('"resource_link"（参照のみ）または "inline"（本文を埋め込んだ）'),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ from, to, inline }) => {
      const span = daysBetween(from, to);
      if (Number.isNaN(span)) {
        return toolError("from / to には実在する日付を指定してください（例: 2026-08-03）。");
      }
      if (span <= 0) {
        return toolError(`from（${from}）は to（${to}）以前の日付を指定してください。`);
      }
      if (span > MAX_RANGE_DAYS) {
        return toolError(
          `書き出せる期間は最長 ${MAX_RANGE_DAYS} 日です（指定された期間は ${span} 日）。`,
        );
      }

      const rows = buildReportRows(from, to);
      const csv = toCsv(rows);
      const byteSize = byteSizeOf(csv);
      const totalHours = sumHours(rows);
      // URI はスキームと階層で「何者か」が分かるように設計する（URI 設計はセッション6）
      const uri = `report://weekly/${from}_${to}.csv`;
      const embed = inline && byteSize <= MAX_INLINE_BYTES;

      const summary = embed
        ? `${from} 〜 ${to} の稼働記録 ${rows.length} 件（合計 ${totalHours} 時間）を CSV にしました。本文はこのレスポンスに含まれています。`
        : `${from} 〜 ${to} の稼働記録 ${rows.length} 件（合計 ${totalHours} 時間）を CSV にしました。本文（${byteSize} バイト）は ${uri} を読み取ってください。`;

      const body = embed
        ? ({
            // 埋め込みリソース：本文をそのまま渡す
            type: "resource" as const,
            resource: { uri, mimeType: "text/csv", text: csv },
          } as const)
        : ({
            // 参照だけ渡す。name は機械的な識別子、title は人間向けの表示名
            type: "resource_link" as const,
            uri,
            name: `${from}_${to}.csv`,
            title: "週次稼働レポート（CSV）",
            mimeType: "text/csv",
            description: `${from} 〜 ${to} の稼働記録 ${rows.length} 件（${byteSize} バイト）`,
          } as const);

      return {
        content: [{ type: "text", text: summary }, body],
        structuredContent: {
          uri,
          rows: rows.length,
          totalHours,
          byteSize,
          delivery: embed ? "inline" : "resource_link",
        },
      };
    },
  );
}
