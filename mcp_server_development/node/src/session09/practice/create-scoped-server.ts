/**
 * 問題6: リクエストごとにスコープを解決する docsearch サーバー
 *
 * mid01 のファイルは 1 行も書き換えません。使うのはドメイン層（検証・走査・検索）と、
 * 本文で作った scopeRepository() だけです。
 *
 * 設計の要点は 1 つ：
 *   「リポジトリ」を注入するのではなく「スコープを解決する関数」を注入する。
 * 起動時に固定した依存には、リクエストごとに変わる境界を後から差し込めません。
 */
import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import {
  DocAccessError,
  createDocRepository,
  type DocRepository,
} from "../../mid01/domain/doc-repository.js";
import {
  DEFAULT_LIMIT,
  MAX_LIMIT,
  MAX_QUERY_LENGTH,
  searchDocuments,
} from "../../mid01/domain/search.js";
import type { CallContext } from "../client-features.js";
import { WHOLE_SCOPE, resolveScopeFromRoots, scopeRepository, type DocScope } from "../domain/doc-scope.js";

export const DOC_TEMPLATE = "docs://{+path}";

/** 境界の問題であることを表す例外。ツールでは isError に、リソースでは -32602 に翻訳する */
export class ScopeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ScopeError";
  }
}

/** スコープの解決手順。テストからは固定値を返す関数を渡せる */
export type ResolveScope = (server: McpServer, context: CallContext) => Promise<DocScope>;

/** roots からスコープを解決する既定の実装 */
export function resolveScopeFromClientRoots(docsRoot: string): ResolveScope {
  return async (server, context) => {
    if (server.server.getClientCapabilities()?.roots === undefined) {
      // roots が使えないクライアントでは、サーバー設定の境界だけを使う（劣化）
      return WHOLE_SCOPE;
    }
    const listed = await server.server.listRoots(undefined, {
      relatedRequestId: context.relatedRequestId,
      signal: context.signal,
      timeout: 5_000,
    });
    const resolved = resolveScopeFromRoots(docsRoot, listed.roots);
    if (!resolved.ok) {
      throw new ScopeError(
        "クライアントが許可した作業ディレクトリ（roots）に、" +
          "このサーバーが公開しているドキュメントの場所が含まれていません。",
      );
    }
    return resolved.scope;
  };
}

export type ScopedServerOptions = {
  readonly docsRoot: string;
  readonly resolveScope: ResolveScope;
};

export function createScopedDocSearchServer(options: ScopedServerOptions): McpServer {
  const base = createDocRepository(options.docsRoot);
  // 名前は変えない（ホストの許可設定に紐づく）。境界の実装が変わったので version を上げる
  const server = new McpServer({ name: "docsearch", version: "0.3.0" });

  /** ここが答え。リクエストごとに解決する */
  async function repositoryFor(context: CallContext): Promise<DocRepository> {
    return scopeRepository(base, await options.resolveScope(server, context));
  }

  server.registerTool(
    "search_documents",
    {
      title: "社内ドキュメントの全文検索",
      description:
        "社内ドキュメント（Markdown）を全文検索し、一致した文書への参照を返します。" +
        "検索対象は、クライアントが roots で許可したディレクトリに限られます。" +
        "本文はレスポンスに含めません。docs:// の URI を resources/read で読み取ってください。",
      inputSchema: {
        query: z.string().min(1).max(MAX_QUERY_LENGTH).describe("検索語（空白区切りで AND 検索）"),
        limit: z
          .number()
          .int()
          .min(1)
          .max(MAX_LIMIT)
          .optional()
          .describe(`返す件数の上限（1〜${MAX_LIMIT}、既定 ${DEFAULT_LIMIT}）`),
        directory: z.string().max(64).optional().describe("検索対象を 1 つのディレクトリに絞る"),
      },
      outputSchema: {
        query: z.string(),
        directory: z.string().optional(),
        totalMatched: z.number().int(),
        returned: z.number().int(),
        truncated: z.boolean(),
        results: z.array(
          z.object({
            path: z.string(),
            uri: z.string(),
            title: z.string(),
            score: z.number(),
            matchCount: z.number().int(),
            snippet: z.string(),
          }),
        ),
      },
      // mid01 と同じ注釈（sampling を使わないので openWorldHint は false のまま）
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async ({ query, limit, directory }, extra) => {
      const context: CallContext = { relatedRequestId: extra.requestId, signal: extra.signal };

      let repository: DocRepository;
      try {
        repository = await repositoryFor(context);
      } catch (error) {
        if (error instanceof ScopeError) {
          // 境界の問題は「利用者が直せる失敗」なので isError で返す
          return toolError(error.message);
        }
        throw toMcpError(error);
      }

      const outcome = searchDocuments(repository, { query, limit, directory });
      if (!outcome.ok) {
        return toolError(outcome.message);
      }
      const { result } = outcome;

      return {
        content: [
          {
            type: "text" as const,
            text: `「${result.query}」に ${result.totalMatched} 件一致しました。`,
          },
          ...result.hits.map((hit) => ({
            type: "resource_link" as const,
            uri: hit.uri,
            name: hit.path,
            title: hit.title,
            mimeType: "text/markdown",
            description: `スコア ${hit.score} / 抜粋: ${hit.snippet}`,
          })),
        ],
        structuredContent: {
          query: result.query,
          ...(result.directory === undefined ? {} : { directory: result.directory }),
          totalMatched: result.totalMatched,
          returned: result.returned,
          truncated: result.truncated,
          results: result.hits.map((hit) => ({
            path: hit.path,
            uri: hit.uri,
            title: hit.title,
            score: hit.score,
            matchCount: hit.matchCount,
            snippet: hit.snippet,
          })),
        },
      };
    },
  );

  server.registerResource(
    "document",
    new ResourceTemplate(DOC_TEMPLATE, {
      // 一覧も境界の内側だけを返す。list と read で範囲が食い違うと混乱する
      list: async (extra) => {
        const repository = await repositoryFor({
          relatedRequestId: extra.requestId,
          signal: extra.signal,
        });
        return {
          resources: repository.listDocuments().map((meta) => ({
            uri: meta.uri,
            name: meta.relativePath,
            title: meta.title,
            mimeType: "text/markdown",
            description: `${meta.lineCount} 行 / ${meta.byteSize} バイト`,
          })),
        };
      },
      // 補完はこの問題では省略する（境界の話に集中するため）
    }),
    {
      title: "社内ドキュメント",
      description:
        "社内ドキュメント 1 件の本文を Markdown で返します。" +
        "読み取れるのは、クライアントが roots で許可したディレクトリの中だけです。",
      mimeType: "text/markdown",
    },
    async (_uri, variables, extra) => {
      const repository = await repositoryFor({
        relatedRequestId: extra.requestId,
        signal: extra.signal,
      });
      const raw = firstValue(variables["path"]);
      try {
        const document = repository.readDocument(raw);
        return {
          contents: [{ uri: document.uri, mimeType: "text/markdown", text: document.text }],
        };
      } catch (error) {
        throw toMcpError(error);
      }
    },
  );

  return server;
}

function toolError(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

function firstValue(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

/** mid01 の toMcpError() は非公開なので、同じ翻訳をここに書く */
function toMcpError(error: unknown): McpError {
  if (error instanceof DocAccessError || error instanceof ScopeError) {
    return new McpError(ErrorCode.InvalidParams, error.message);
  }
  console.error("[q6] 予期しないエラー:", error);
  return new McpError(ErrorCode.InternalError, "ドキュメントの読み取りに失敗しました。");
}
