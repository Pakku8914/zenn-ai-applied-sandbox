/**
 * 問題4 の解答：別名に対応した補完と読み取り
 *
 * 同じ URI テンプレートを 2 回登録できないため、本文のファクトリは呼ばずに
 * このファイルで McpServer を組み立て直しています。
 *
 * 要点は「候補を出す処理」と「値を解決する処理」を 1 つの関数に寄せることです。
 * 別々に書くと、候補に出た値が読めない不整合が起きます。
 */
import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";

import { TERM_SLUG_PATTERN, completeTermSlugs, findTerm, renderTermMarkdown } from "../data.js";

/** 別名 → 正式スラッグ。data.ts を変更せずに済むよう、この解答ファイル側で持ちます */
const ALIASES: Readonly<Record<string, string>> = {
  ct: "cycle-time",
  lt: "lead-time",
  point: "story-point",
  sp: "story-point",
  "work-in-progress": "wip",
};

/** 補完で返す上限。仕様上の上限（100 件）とは別に、サーバー側の判断で絞ります */
const MAX_COMPLETION_VALUES = 20;

export function createDashboardServerQ4(): McpServer {
  const server = new McpServer({ name: "team-dashboard-q4", version: "0.3.0" });

  server.registerResource(
    "glossary_term",
    new ResourceTemplate("glossary://{term}", {
      list: undefined,
      complete: { term: (value) => completeWithAliases(value) },
    }),
    {
      title: "社内用語辞書（別名対応）",
      description:
        "社内用語 1 件の定義を Markdown で返します。" +
        "term には正式なスラッグ（例: story-point）に加えて別名（例: sp）も指定できます。" +
        `候補は completion/complete で取得できます（サーバー側の判断で最大 ${MAX_COMPLETION_VALUES} 件に絞るため、` +
        "候補に出ていない別名も存在しえます）。",
      mimeType: "text/markdown",
    },
    async (_uri, variables) => {
      const slug = resolveSlug(firstValue(variables["term"]));
      const entry = slug === undefined ? undefined : findTerm(slug);
      if (entry === undefined) {
        // 入力値を含めない（反射による情報漏えいとログ汚染を避ける）
        throw new McpError(
          ErrorCode.InvalidParams,
          "指定された用語は辞書にありません。" +
            `有効なスラッグ: ${completeTermSlugs("").join(", ")}`,
        );
      }
      // 別名で読まれても、返す URI は正式スラッグの正規形にする
      return {
        contents: [
          {
            uri: `glossary://${entry.slug}`,
            mimeType: "text/markdown",
            text: renderTermMarkdown(entry),
          },
        ],
      };
    },
  );

  return server;
}

function firstValue(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

/**
 * 別名を含めて正式スラッグに解決する。
 * ① 1 回だけデコード ② 許可リストに照合 ③ 別名を変換 ④ 実在確認
 */
function resolveSlug(raw: string): string | undefined {
  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    return undefined;
  }
  if (!TERM_SLUG_PATTERN.test(decoded)) {
    return undefined;
  }
  const canonical = ALIASES[decoded] ?? decoded;
  return findTerm(canonical) === undefined ? undefined : canonical;
}

/**
 * 候補：正式スラッグ（辞書順）→ 別名（辞書順）の順に並べ、上限で切る。
 * 「正式を先に」並べるのは、ユーザーに正式名を覚えてもらうためです。
 */
function completeWithAliases(value: string): string[] {
  const needle = value.trim().toLowerCase();
  const official = completeTermSlugs(needle);
  const aliases = Object.keys(ALIASES)
    .filter((alias) => alias.startsWith(needle))
    .sort((a, b) => a.localeCompare(b));
  return [...official, ...aliases].slice(0, MAX_COMPLETION_VALUES);
}
