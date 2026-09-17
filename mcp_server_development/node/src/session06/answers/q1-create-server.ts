/**
 * 問題1 の解答：静的リソース glossary://index を追加する
 *
 * 本文の createDashboardServer() が返す McpServer に registerResource を
 * 追記するだけで拡張できます。コードを 1 行もコピーしないのが要点です。
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { createDashboardServer } from "../create-server.js";
import { completeTermSlugs, findTerm, glossary } from "../data.js";

export function createDashboardServerQ1(): McpServer {
  const server = createDashboardServer();
  registerGlossaryIndex(server);
  return server;
}

function registerGlossaryIndex(server: McpServer): void {
  server.registerResource(
    "glossary_index",
    "glossary://index",
    {
      title: "社内用語辞書の索引",
      description:
        "社内用語辞書に登録されている用語の一覧（スラッグ・用語・分類）を Markdown の表で返します。" +
        "個別の定義は glossary://{term} を読み取ってください（term にはこの表のスラッグを指定します）。",
      mimeType: "text/markdown",
    },
    async (uri) => ({
      contents: [{ uri: uri.href, mimeType: "text/markdown", text: renderIndex() }],
    }),
  );
}

/** 索引の Markdown を組み立てる。並び順は補完と同じ（スラッグ昇順）に揃える */
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
