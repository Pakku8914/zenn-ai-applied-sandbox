/**
 * 横断復習2 問題4 ― 社内お知らせ掲示板サーバー（定義）
 *
 * 公開するもの
 *   ツール      : search_notices（読み取り専用・ヒットを resource_link で返す）
 *   テンプレート: notice://{slug}（本文を Markdown で返す・slug の補完つき）
 *
 * この 2 つはセットです。ツールが返した URI をテンプレートが読めるようにして
 * 初めて、resource_link は約束を果たします（セッション5 の宿題の回収）。
 *
 * トランスポートへの接続はここでは行いません（q4-server.ts の責務）。
 */
import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import {
  DEFAULT_LIMIT,
  MAX_LIMIT,
  SLUG_PATTERN,
  completeSlugs,
  findNotice,
  labelOf,
  listSlugs,
  matchNotices,
  renderNoticeMarkdown,
} from "./board.js";

export const NOTICE_TEMPLATE = "notice://{slug}";

export function createNoticeServer(): McpServer {
  const server = new McpServer({ name: "notice-board", version: "0.1.0" });
  registerSearchTool(server);
  registerNoticeResource(server);
  return server;
}

/**
 * 検索ツール。ヒットの本文は返さず、参照（resource_link）だけを返す。
 * 問題5 でも同じ実装を使うため、登録処理を関数として公開しています。
 */
export function registerSearchTool(server: McpServer): void {
  server.registerTool(
    "search_notices",
    {
      title: "社内お知らせの検索",
      description:
        "社内お知らせ掲示板をタイトルと本文の部分一致で検索し、ヒットしたお知らせへの参照（resource_link）を返します。" +
        "本文はレスポンスに含めません。必要なお知らせだけ notice://{slug} を resources/read で読み取ってください。" +
        "読みたいお知らせのスラッグが既に分かっている場合は、検索せず notice://{slug} を直接読んでください。" +
        `既定では上位 ${DEFAULT_LIMIT} 件を返します（最大 ${MAX_LIMIT} 件）。ヒット総数は totalMatches で分かります。`,
      inputSchema: {
        query: z
          .string()
          .min(1)
          .max(100)
          .describe("検索語。お知らせのタイトルと本文を対象に部分一致で探します"),
        limit: z
          .number()
          .int()
          .min(1)
          .max(MAX_LIMIT)
          .default(DEFAULT_LIMIT)
          .describe(
            `返す最大件数（1〜${MAX_LIMIT}、既定 ${DEFAULT_LIMIT}）。ヒット総数は totalMatches を見てください`,
          ),
        category: z
          .enum(["all", "facility", "general", "hr", "it"])
          .default("all")
          .describe(
            "分類で絞り込みます（facility: 設備 / general: 総務 / hr: 人事 / it: 情報システム / all: 絞り込みなし）",
          ),
      },
      outputSchema: {
        query: z.string().describe("検索に使った語"),
        category: z.string().describe("適用した分類フィルタ（all は絞り込みなし）"),
        totalMatches: z.number().int().describe("条件に一致した総件数（limit で切る前の件数）"),
        returned: z.number().int().describe("このレスポンスで返した件数"),
        hits: z
          .array(
            z.object({
              slug: z.string().describe("お知らせのスラッグ"),
              title: z.string().describe("お知らせのタイトル"),
              category: z.string().describe("分類コード"),
              publishedOn: z.string().describe("掲載日（YYYY-MM-DD）"),
              matchedIn: z.string().describe('一致した場所（"title" または "body"）'),
              uri: z.string().describe("本文を読み取る URI（resources/read に渡せます）"),
            }),
          )
          .describe("ヒットしたお知らせ（タイトル一致を先に、その中ではスラッグ昇順）"),
      },
      // 読み取り専用ツールに書くのはこの 2 つだけ（残り 2 つは意味を持たない）
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ query, limit, category }) => {
      const hits = matchNotices(query, category);
      const returned = hits.slice(0, limit);
      const scope = category === "all" ? "すべての分類" : `${labelOf(category)}（${category}）`;

      if (returned.length === 0) {
        // 「0 件」は失敗ではない。isError を付けず、次の行動を促すテキストだけを返す
        return {
          content: [
            {
              type: "text" as const,
              text:
                `「${query}」に一致するお知らせは ${scope} にありません。` +
                "別の語で検索するか、category を all にして絞り込みを外してください。",
            },
          ],
          structuredContent: { query, category, totalMatches: 0, returned: 0, hits: [] },
        };
      }

      const summary =
        `「${query}」に ${hits.length} 件ヒットしました（${scope} / 上位 ${returned.length} 件を返しています）。` +
        "本文はレスポンスに含めていません。必要なお知らせの uri を resources/read で読み取ってください。";

      // 不在票（resource_link）を並べる。name は機械的な識別子、title は人間向けの表示名
      const links = returned.map((hit) => ({
        type: "resource_link" as const,
        uri: `notice://${hit.slug}`,
        name: hit.slug,
        title: hit.title,
        mimeType: "text/markdown",
        description:
          `${labelOf(hit.category)} / ${hit.publishedOn} / ` +
          (hit.matchedIn === "title" ? "タイトル一致" : "本文一致"),
      }));

      return {
        content: [{ type: "text" as const, text: summary }, ...links],
        structuredContent: {
          query,
          category,
          totalMatches: hits.length,
          returned: returned.length,
          hits: returned.map((hit) => ({
            slug: hit.slug,
            title: hit.title,
            category: hit.category,
            publishedOn: hit.publishedOn,
            matchedIn: hit.matchedIn,
            uri: `notice://${hit.slug}`,
          })),
        },
      };
    },
  );
}

/** お知らせ 1 件のリソーステンプレート。search_notices が返す URI を読めるようにする */
export function registerNoticeResource(server: McpServer): void {
  server.registerResource(
    "notice_detail",
    new ResourceTemplate(NOTICE_TEMPLATE, {
      // 件数が増えても一覧が膨らまないように、あえて列挙しない。
      // 見つけ方は「補完」と「検索結果の resource_link」の 2 経路を用意している
      list: undefined,
      complete: {
        // 絞り込みはサーバー側の責務（SDK は返した配列をそのまま values に入れるだけ）
        slug: (value) => completeSlugs(value),
      },
    }),
    {
      title: "社内お知らせ（1 件）",
      description:
        "社内お知らせ 1 件の本文を Markdown で返します。" +
        "slug は英小文字・数字・ハイフンからなるスラッグです（例: summer-holiday）。" +
        "指定できる値は completion/complete で取得できます。条件で探す場合は search_notices を使ってください。",
      mimeType: "text/markdown",
    },
    async (_uri, variables) => {
      // ① 変数を取り出して正規化・検証する（テンプレートに一致しただけでは安全ではない）
      const slug = normalizeSlug(firstValue(variables["slug"]));
      const notice = slug === undefined ? undefined : findNotice(slug);
      if (notice === undefined) {
        // ② リソースの失敗は JSON-RPC エラー。isError はツールだけの仕組み。
        //    受け取った値はエラー文に含めない（攻撃文字列をログ経路に流さない）
        throw new McpError(
          ErrorCode.InvalidParams,
          "指定されたお知らせは存在しません。" +
            `有効なスラッグの例: ${listSlugs().slice(0, 3).join(", ")}（全 ${listSlugs().length} 件）。` +
            "候補は completion/complete で取得できます。",
        );
      }
      // ③ 返す uri は「受け取った uri」ではなく「自分で組み立てた正規形」にする
      return {
        contents: [
          {
            uri: `notice://${notice.slug}`,
            mimeType: "text/markdown",
            text: renderNoticeMarkdown(notice),
          },
        ],
      };
    },
  );
}

/** テンプレート変数は string | string[] で届く。単純展開しか使わないので先頭 1 つを見る */
export function firstValue(value: string | string[] | undefined): string {
  if (Array.isArray(value)) {
    return value[0] ?? "";
  }
  return value ?? "";
}

/**
 * スラッグを正規化して検証する。許可リストに載らない値は undefined。
 *
 * デコードを 1 回だけ行うのが要点です。2 回行うと %252f（%2f の二重エンコード）
 * のような入力を通してしまいます（問題6 で実際に破ります）。
 */
export function normalizeSlug(raw: string): string | undefined {
  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    // 壊れたパーセントエンコード（例: "%zz"）はここで落ちる
    return undefined;
  }
  return SLUG_PATTERN.test(decoded) ? decoded : undefined;
}
