/**
 * 問題4 の解答：export_report に format（csv / json）を足す
 *
 * 要点は 3 つです。
 *   ① 選択肢は z.enum で閉じる（ハンドラに不正値が来ない）
 *   ② 形式に応じて URI の拡張子と mimeType を切り替える
 *   ③ 埋め込みの可否はサーバーの上限が最終判断（呼び出し側の希望より強い）
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import {
  MAX_INLINE_BYTES,
  MAX_RANGE_DAYS,
  buildReportRows,
  byteSizeOf,
  daysBetween,
  sumHours,
  toCsv,
} from "../data.js";

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** 形式ごとの違いを 1 か所に集める（分岐をハンドラに散らさない） */
const FORMATS = {
  csv: { extension: "csv", mimeType: "text/csv" },
  json: { extension: "json", mimeType: "application/json" },
} as const;

export function createExportServer(): McpServer {
  const server = new McpServer({ name: "team-dashboard-q4", version: "0.2.0" });

  server.registerTool(
    "export_report",
    {
      title: "稼働レポートの書き出し",
      description:
        "指定期間の稼働記録を CSV または JSON に書き出し、リソースへの参照（resource_link）を返します。" +
        "本文はレスポンスに含めません。中身が必要な場合は返された URI を読み取ってください。" +
        `inline に true を指定すると本文を埋め込みますが、${MAX_INLINE_BYTES} バイトを超える場合はサーバーの判断で参照に切り替わります。` +
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
        format: z
          .enum(["csv", "json"])
          .default("csv")
          .describe("出力形式。csv は表計算ソフト向け、json はプログラム処理向け。既定は csv。"),
        inline: z
          .boolean()
          .default(false)
          .describe(
            `true にすると本文をレスポンスに埋め込みます（${MAX_INLINE_BYTES} バイトまで）。既定は false（参照のみ）。`,
          ),
      },
      outputSchema: {
        uri: z.string().describe("生成したリソースの URI"),
        format: z.string().describe("実際に使った出力形式"),
        mimeType: z.string().describe("本文の MIME タイプ"),
        rows: z.number().int().describe("データ行数"),
        totalHours: z.number().describe("期間内の合計稼働時間"),
        byteSize: z.number().int().describe("本文のバイト数（UTF-8）"),
        delivery: z.string().describe('"resource_link" または "inline"'),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ from, to, format, inline }) => {
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
      const spec = FORMATS[format];
      // JSON は 1 行で出す（整形すると読みやすいが、バイト数が 2 倍近くになる）
      const bodyText = format === "csv" ? toCsv(rows) : JSON.stringify(rows);
      const byteSize = byteSizeOf(bodyText);
      const uri = `report://weekly/${from}_${to}.${spec.extension}`;
      const embed = inline && byteSize <= MAX_INLINE_BYTES;

      const notice =
        inline && !embed
          ? `本文が上限（${MAX_INLINE_BYTES} バイト）を超えたため、参照だけを返します。`
          : "";
      const summary =
        `${from} 〜 ${to} の稼働記録 ${rows.length} 件（合計 ${sumHours(rows)} 時間）を ${format} にしました。` +
        (embed ? "本文はこのレスポンスに含まれています。" : `本文（${byteSize} バイト）は ${uri} を読み取ってください。${notice}`);

      const body = embed
        ? ({
            type: "resource" as const,
            resource: { uri, mimeType: spec.mimeType, text: bodyText },
          } as const)
        : ({
            type: "resource_link" as const,
            uri,
            name: `${from}_${to}.${spec.extension}`,
            title: `稼働レポート（${format.toUpperCase()}）`,
            mimeType: spec.mimeType,
            description: `${from} 〜 ${to} の稼働記録 ${rows.length} 件（${byteSize} バイト）`,
          } as const);

      return {
        content: [{ type: "text", text: summary }, body],
        structuredContent: {
          uri,
          format,
          mimeType: spec.mimeType,
          rows: rows.length,
          totalHours: sumHours(rows),
          byteSize,
          delivery: embed ? "inline" : "resource_link",
        },
      };
    },
  );

  return server;
}

function toolError(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}
