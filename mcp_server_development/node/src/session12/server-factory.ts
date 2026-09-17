/**
 * スコープに応じたサーバー定義の組み立て
 *
 * 中間プロジェクト1 の create-server.ts は 1 行も書き換えません。
 * 返ってきた McpServer に「管理ツールを足すかどうか」だけを、
 * そのセッションのトークンのスコープで決めます。
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { createDocSearchServer } from "../mid01/create-server.js";
import { createDocRepository } from "../mid01/domain/doc-repository.js";
import { SCOPE_DOCS_ADMIN, currentAuth, denyIfMissingScope } from "./scopes.js";

export type ProtectedFactoryOptions = { readonly docsRoot: string };

export function createProtectedServerFactory(options: ProtectedFactoryOptions): () => McpServer {
  return () => {
    const server = createDocSearchServer({ docsRoot: options.docsRoot });
    // このファクトリは initialize リクエストの処理中に呼ばれるので、
    // AsyncLocalStorage にはそのリクエストのトークンの文脈が入っています
    const auth = currentAuth();
    if (auth !== undefined && auth.scopes.includes(SCOPE_DOCS_ADMIN)) {
      registerAdminTools(server, options.docsRoot);
    }
    return server;
  };
}

function registerAdminTools(server: McpServer, docsRoot: string): void {
  server.registerTool(
    "reindex_documents",
    {
      title: "検索インデックスの再構築（管理者用）",
      description:
        "公開ディレクトリを走査し直して検索インデックスを作り直します。" +
        "権限 docs:admin が必要です。検索だけをしたい場合は search_documents を使ってください。",
      inputSchema: {
        directory: z
          .string()
          .max(64)
          .optional()
          .describe("再構築の対象を 1 つのディレクトリに絞る場合に指定します（例: guides）"),
      },
      // 読み取り専用ではないので readOnlyHint は false。ただしデータを壊さないので destructive でもない
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async ({ directory }) => {
      // ★ 二重チェック。tools/list に出していないことは「守っている」ことではない。
      //   セッションが張られたあとにスコープの狭いトークンで呼ばれる経路もありえます
      const denied = denyIfMissingScope("reindex_documents");
      if (denied !== undefined) {
        return denied;
      }

      const startedAt = Date.now();
      const repository = createDocRepository(docsRoot);
      const documents = repository
        .listDocuments()
        .filter((meta) => directory === undefined || meta.relativePath.startsWith(`${directory}/`));
      return {
        content: [
          {
            type: "text" as const,
            text:
              `インデックスを再構築しました（対象 ${documents.length} 件 / ${Date.now() - startedAt}ms）。` +
              (directory === undefined ? "" : `対象ディレクトリ: ${directory}`),
          },
        ],
      };
    },
  );
}
