/**
 * 横断復習2 問題5 ― お知らせダイジェストのプロンプトを追加する
 *
 * 問題4 のツールとリソースは、登録関数を呼んで再利用します。
 * 検索ロジックを 2 か所に書かないのが要点です（プロンプトとツールで結果が
 * 食い違うと、ユーザーには原因が分かりません）。
 */
import { completable } from "@modelcontextprotocol/sdk/server/completable.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import {
  CATEGORY_CODES,
  DEFAULT_LIMIT,
  MAX_INLINE_BYTES,
  byteSizeOf,
  completeCategories,
  findNotice,
  labelOf,
  matchNotices,
  renderNoticeMarkdown,
  toCategoryFilter,
} from "./board.js";
import { registerNoticeResource, registerSearchTool } from "./q4-create-server.js";

export function createNoticeServerQ5(): McpServer {
  const server = new McpServer({ name: "notice-board", version: "0.2.0" });
  registerSearchTool(server);
  registerNoticeResource(server);
  registerDigestPrompt(server);
  return server;
}

/**
 * お知らせダイジェストの下書きプロンプト。
 *
 * プロンプトの引数はプロトコル上すべて文字列で届きます（prompts/list に載るのは
 * 名前・説明・必須フラグだけ）。だから「候補を返す補完」と「値を弾く検証」を
 * 別々に書く必要があります。
 */
function registerDigestPrompt(server: McpServer): void {
  server.registerPrompt(
    "notice_digest",
    {
      title: "お知らせダイジェストの下書き",
      description:
        "検索語に一致する社内お知らせを集め、共有用のダイジェストを書く指示と資料を組み立てます。" +
        "ユーザーがメニューから選んで起動する定型作業です（モデルが自発的に呼ぶことはありません）。",
      argsSchema: {
        query: z
          .string()
          .min(1)
          .max(100)
          .describe("検索語。お知らせのタイトルと本文を対象に部分一致で探します"),
        // completable() で包むと、その引数に補完が付く（包み忘れても登録エラーにはならない）
        category: completable(
          z.string().describe(`分類コード（${CATEGORY_CODES.join(" / ")}）。all は絞り込みなし`),
          (value) => completeCategories(value),
        ),
        attach: z
          .enum(["inline", "link"])
          .describe("資料の渡し方（inline: 本文を埋め込む / link: URI だけ渡す）"),
      },
    },
    ({ query, category, attach }) => {
      // 補完は「親切」、検証は「防御」。候補外の値で呼ばれることは普通にある
      const filter = toCategoryFilter(category);
      if (filter === undefined) {
        // プロンプトの失敗は JSON-RPC エラーだけ（isError は使えない）。
        // 受け取った値はエラー文に含めない
        throw new McpError(
          ErrorCode.InvalidParams,
          `category には ${CATEGORY_CODES.join(" / ")} のいずれかを指定してください。` +
            "候補は completion/complete で取得できます。",
        );
      }

      const hits = matchNotices(query, filter).slice(0, DEFAULT_LIMIT);
      const scope = filter === "all" ? "すべての分類" : `${labelOf(filter)}（${filter}）`;
      const top = hits[0];

      if (top === undefined) {
        return {
          description: `「${query}」のダイジェスト（該当なし）`,
          messages: [
            {
              role: "user" as const,
              content: {
                type: "text" as const,
                text:
                  `「${query}」に一致する社内お知らせは ${scope} にありませんでした。` +
                  "検索語を変えるか、category を all にしてもう一度実行するようユーザーへ案内してください。",
              },
            },
          ],
        };
      }

      const instruction = [
        `次の社内お知らせ ${hits.length} 件をもとに、社内共有用のダイジェストを作成してください。`,
        "",
        "## 対象",
        `- 検索語: ${query}`,
        `- 分類: ${scope}`,
        ...hits.map(
          (hit) => `- ${hit.slug}: ${hit.title}（${labelOf(hit.category)} / ${hit.publishedOn}）`,
        ),
        "",
        "## 書き方",
        "- 1 件 1 行で、締切や実施日などの日付を必ず含めてください",
        "- 掲載日の新しいものを先に並べてください",
        "- 本文に書かれていないことを補わないでください",
        "",
        "## 資料",
        "最も関連が高い 1 件だけを添えています。ほかの件の本文が必要なら notice://{slug} を読み取ってください。",
      ].join("\n");

      const notice = findNotice(top.slug);
      const markdown = notice === undefined ? "" : renderNoticeMarkdown(notice);
      const uri = `notice://${top.slug}`;
      // 呼び出し側の希望（attach）より、サーバーの上限が優先される
      const embed = attach === "inline" && byteSizeOf(markdown) <= MAX_INLINE_BYTES;

      const attachment = embed
        ? ({
            type: "resource",
            resource: { uri, mimeType: "text/markdown", text: markdown },
          } as const)
        : ({
            type: "text",
            text: `最も関連が高いお知らせの本文は添付していません。${uri} を resources/read で読み取ってください。`,
          } as const);

      return {
        description: `「${query}」のダイジェスト下書き（${hits.length} 件 / ${attach}）`,
        messages: [
          { role: "user" as const, content: { type: "text" as const, text: instruction } },
          { role: "user" as const, content: attachment },
        ],
      };
    },
  );
}
