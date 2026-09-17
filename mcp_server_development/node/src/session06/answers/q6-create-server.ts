/**
 * 問題6 の解答：メンバー別レポートの下書きプロンプト
 *
 * 問題1 のファクトリ（glossary://index を足したもの）に追記します。
 * プロンプトから埋め込む索引の中身と、リソースとして読める索引が
 * 同じ URI を指すようにするためです。
 *
 * プロンプト引数はプロトコル上すべて文字列である、という制約への対処が主題です。
 */
import { completable } from "@modelcontextprotocol/sdk/server/completable.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import {
  MAX_INLINE_BYTES,
  buildReportRows,
  byteSizeOf,
  completeTermSlugs,
  findMember,
  findTerm,
  glossary,
  listWeekStarts,
  members,
  sumHours,
  toCsv,
  weekEndOf,
} from "../data.js";
import { createDashboardServerQ1 } from "./q1-create-server.js";

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

type PromptContent =
  | { type: "text"; text: string }
  | { type: "resource"; resource: { uri: string; mimeType: string; text: string } };

export function createDashboardServerQ6(): McpServer {
  const server = createDashboardServerQ1();
  registerMemberReportPrompt(server);
  return server;
}

function registerMemberReportPrompt(server: McpServer): void {
  server.registerPrompt(
    "member_report_draft",
    {
      title: "メンバー別レポート下書き",
      description:
        "メンバー 1 人の 1 週間の稼働実績から、振り返りメモの下書きを作る指示と資料を組み立てます。" +
        "対象週の終了日は week_start（月曜日）から自動で求めます。",
      argsSchema: {
        member_id: completable(
          z
            .string()
            .regex(/^m-\d{3}$/, "m-001 のような形式で指定してください")
            .describe("対象メンバーの ID（例: m-003）"),
          (value) => members.map((member) => member.id).filter((id) => id.startsWith(value)),
        ),
        week_start: completable(
          z
            .string()
            .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
            .describe("対象週の月曜日（YYYY-MM-DD）"),
          (value) => listWeekStarts().filter((monday) => monday.startsWith(value)),
        ),
        include_glossary: z
          .string()
          .optional()
          .describe('"true" を指定すると社内用語辞書の索引を添付します（既定は添付しない）'),
      },
    },
    ({ member_id, week_start, include_glossary }) => {
      const member = findMember(member_id);
      if (member === undefined) {
        // 形式は正しいが実在しない → プロンプトでは JSON-RPC エラーしか返せない
        throw new McpError(
          ErrorCode.InvalidParams,
          `メンバー ID ${member_id} は存在しません。有効な ID: ${members
            .map((item) => item.id)
            .join(", ")}`,
        );
      }

      const weekEnd = weekEndOf(week_start);
      const rows = buildReportRows(week_start, weekEnd).filter(
        (row) => row.memberId === member_id,
      );
      const csv = toCsv(rows);
      const csvBytes = byteSizeOf(csv);
      const csvUri = `report://member/${member_id}/${week_start}_${weekEnd}.csv`;

      // プロトコル上は文字列なので、"true" 以外はすべて false として扱う。
      // 不正値でエラーにしないのは、ホストの UI が自由入力で
      // 「True」「1」などを送ってくる可能性があり、下書きを作れないほどの問題ではないため。
      const includeGlossary = include_glossary === "true";

      const instruction = [
        `${member.name}（${member.id} / ${member.team}）の ${week_start}〜${weekEnd} の振り返りメモの下書きを作成してください。`,
        "",
        "## 前提",
        `- この週の稼働記録: ${rows.length} 件 / 合計 ${sumHours(rows)} 時間`,
        `- 週の稼働可能時間: ${member.weeklyCapacityHours} 時間`,
        "",
        "## 書き方",
        "- できたこと・詰まったこと・来週やることの 3 点に整理してください",
        "- 評価や反省ではなく、事実と次の行動を書いてください",
        includeGlossary
          ? "- 添付した用語辞書の索引にある言葉を使ってください"
          : "- 用語が分からない場合は glossary://{term} リソースを参照してください",
      ].join("\n");

      const messages: { role: "user"; content: PromptContent }[] = [
        { role: "user", content: { type: "text", text: instruction } },
      ];

      // 明細は埋め込むが、上限を超えたら URI だけを渡す
      messages.push(
        csvBytes <= MAX_INLINE_BYTES
          ? {
              role: "user",
              content: { type: "resource", resource: { uri: csvUri, mimeType: "text/csv", text: csv } },
            }
          : {
              role: "user",
              content: {
                type: "text",
                text: `明細（${csvBytes} バイト）は大きいため添付していません。`,
              },
            },
      );

      if (includeGlossary) {
        messages.push({
          role: "user",
          content: {
            type: "resource",
            resource: { uri: "glossary://index", mimeType: "text/markdown", text: renderIndex() },
          },
        });
      }

      return {
        description: `${member.name} の ${week_start}〜${weekEnd} 振り返りメモ下書き`,
        messages,
      };
    },
  );
}

/** 問題1 と同じ索引。プロンプトとリソースで同じ内容を返すために関数を共有します */
function renderIndex(): string {
  const rows = completeTermSlugs("").map((slug) => {
    const entry = findTerm(slug);
    return `| ${slug} | ${entry?.term ?? "-"} | ${entry?.category ?? "-"} |`;
  });
  return [
    `# 社内用語辞書（${glossary.length} 件）`,
    "",
    "| スラッグ | 用語 | 分類 |",
    "| :--- | :--- | :--- |",
    ...rows,
  ].join("\n");
}
