/**
 * セッション9 のサーバー定義 ―― mid01 のサーバーに summarize_results を足す
 *
 * mid01 のファイルは 1 行も書き換えません（import するだけ）。
 * サーバー名は変えません（ホストの許可設定はサーバー名に紐づくため）。version だけ上げます。
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { createDocSearchServer } from "../mid01/create-server.js";
import { createDocRepository, type DocRepository } from "../mid01/domain/doc-repository.js";
import {
  MAX_LIMIT,
  MAX_QUERY_LENGTH,
  searchDocuments,
  type SearchResult,
} from "../mid01/domain/search.js";
import {
  askNarrowing,
  detectSupport,
  fetchRoots,
  installRootsCache,
  requestSummary,
  type CallContext,
  type RootsCache,
} from "./client-features.js";
import {
  describeScope,
  resolveScopeFromRoots,
  scopeRepository,
  WHOLE_SCOPE,
  type DocScope,
} from "./domain/doc-scope.js";
import {
  buildExcerptDigest,
  buildSummaryPromptText,
  collectExcerpts,
  type SkipReason,
  type SummaryMode,
} from "./domain/summary-prompt.js";

export const SERVER_VERSION_09 = "0.2.0";
/** これ以下のヒット数なら、ユーザーに尋ねずに全部要約する */
export const AMBIGUOUS_THRESHOLD = 3;
/** elicitation の選択肢に混ぜる「絞り込まない」を表す値 */
export const NARROW_ALL = "all";

export function createSession09Server(options: { docsRoot: string }): McpServer {
  const server = createDocSearchServer({
    docsRoot: options.docsRoot,
    serverVersion: SERVER_VERSION_09,
  });
  const baseRepository = createDocRepository(options.docsRoot);
  const rootsCache = installRootsCache(server);
  registerSummarizeResults(server, baseRepository, options.docsRoot, rootsCache);
  return server;
}

function registerSummarizeResults(
  server: McpServer,
  baseRepository: DocRepository,
  docsRoot: string,
  rootsCache: RootsCache,
): void {
  server.registerTool(
    "summarize_results",
    {
      title: "検索結果の要約",
      description:
        "社内ドキュメントを検索し、その結果をクライアント側の LLM で要約して返します。" +
        "クライアントが sampling に対応していない場合は、要約せずに抜粋の一覧を返します" +
        "（結果の形は同じで、summarySource で区別できます）。" +
        "検索結果の一覧だけが欲しい場合は search_documents を使ってください。",
      inputSchema: {
        query: z
          .string()
          .min(1)
          .max(MAX_QUERY_LENGTH)
          .describe("検索語。空白区切りで複数指定すると AND 検索になります"),
        directory: z
          .string()
          .max(64)
          .optional()
          .describe(
            "検索対象を 1 つのディレクトリに絞る場合に指定します。" +
              "省略した場合、候補が複数あるときはユーザーに確認します",
          ),
        limit: z
          .number()
          .int()
          .min(1)
          .max(MAX_LIMIT)
          .optional()
          .describe("要約の材料にする文書数の上限（1〜20、既定 5）"),
        mode: z
          .enum(["quick", "careful"])
          .optional()
          .describe("quick は速さと費用を優先、careful は精度を優先します（既定 quick）"),
      },
      outputSchema: {
        query: z.string().describe("実際に検索に使った語"),
        mode: z.enum(["quick", "careful"]).describe("要約に使った優先度プロファイル"),
        scopeSource: z
          .enum(["server-config", "roots"])
          .describe("検索範囲の決まり方。roots はクライアントの申告で絞り込んだことを表す"),
        scopeDirectories: z
          .array(z.string())
          .describe("roots で絞り込まれたディレクトリ。空配列は公開ディレクトリ全体"),
        narrowedBy: z
          .enum(["argument", "elicitation", "none"])
          .describe("ディレクトリの絞り込みが何によって決まったか"),
        narrowedTo: z.string().optional().describe("絞り込んだディレクトリ"),
        totalMatched: z.number().int().describe("一致した文書の総数"),
        returned: z.number().int().describe("要約の材料にした件数"),
        truncated: z.boolean().describe("上限で打ち切ったか"),
        summary: z.string().describe("要約、または抜粋の一覧"),
        summarySource: z
          .enum(["sampling", "excerpt"])
          .describe("summary の作られ方。excerpt は劣化経路で作ったことを表す"),
        model: z
          .string()
          .optional()
          .describe("sampling でクライアントが実際に使ったモデル。サーバーは指定していない"),
        skipReason: z
          .enum(["unsupported", "call_failed", "non_text_response"])
          .optional()
          .describe("sampling を使わなかった理由"),
        degraded: z
          .object({ sampling: z.boolean(), roots: z.boolean(), elicitation: z.boolean() })
          .describe("どのクライアント機能が使えなかったか"),
        results: z
          .array(
            z.object({
              path: z.string(),
              uri: z.string(),
              title: z.string(),
              score: z.number(),
              snippet: z.string(),
            }),
          )
          .describe("要約の材料にした文書（スコア降順・パス昇順）"),
      },
      // 注釈は search_documents からコピーしない。性質が違う
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        // LLM の応答は毎回同じとは限らず、ユーザーへの確認も挟まる
        idempotentHint: false,
        // クライアント越しに外部のモデルへ依存する
        openWorldHint: true,
      },
    },
    async ({ query, directory, limit, mode }, extra) => {
      const callContext: CallContext = {
        relatedRequestId: extra.requestId,
        signal: extra.signal,
      };
      const support = detectSupport(server);
      const summaryMode: SummaryMode = mode ?? "quick";
      const degraded = { sampling: false, roots: false, elicitation: false };

      // ① 境界を決める（roots）
      let scope: DocScope = WHOLE_SCOPE;
      if (!support.roots) {
        degraded.roots = true;
      } else {
        const fetched = await fetchRoots(server, rootsCache, callContext);
        if (!fetched.ok) {
          degraded.roots = true;
        } else {
          const resolved = resolveScopeFromRoots(docsRoot, fetched.roots);
          if (!resolved.ok) {
            // 「全体で検索する」に倒さない。境界が効かないまま動くほうが危険
            return toolError(
              "クライアントが許可した作業ディレクトリ（roots）に、" +
                "このサーバーが公開しているドキュメントの場所が含まれていません。" +
                "作業ディレクトリを追加してから、もう一度実行してください。",
            );
          }
          scope = resolved.scope;
        }
      }
      const repository = scopeRepository(baseRepository, scope);

      // ② 検索（この時点でスコープは効いている）
      const first = searchDocuments(repository, { query, limit, directory });
      if (!first.ok) {
        return toolError(first.message);
      }
      let result: SearchResult = first.result;

      // ③ 曖昧なら尋ねる（elicitation）
      let narrowedBy: "argument" | "elicitation" | "none" =
        directory === undefined ? "none" : "argument";
      const candidates = repository.listDirectories();
      if (
        directory === undefined &&
        result.totalMatched > AMBIGUOUS_THRESHOLD &&
        candidates.length >= 2
      ) {
        if (!support.elicitation) {
          degraded.elicitation = true;
        } else {
          const answer = await askNarrowing(
            server,
            {
              message: `「${query}」に ${result.totalMatched} 件一致しました。対象を絞り込みますか。`,
              candidates,
              allValue: NARROW_ALL,
            },
            callContext,
          );
          if (answer.kind === "cancelled") {
            // 中断は「やめる」。ここで要約を作ると余計な費用が出る
            return toolError("ユーザーが操作を中断したため、要約を作成しませんでした。");
          }
          if (answer.kind === "failed" || answer.kind === "invalid") {
            degraded.elicitation = true;
          } else if (answer.kind === "answered" && answer.value !== NARROW_ALL) {
            const narrowed = searchDocuments(repository, {
              query,
              limit,
              directory: answer.value,
            });
            if (!narrowed.ok) {
              return toolError(narrowed.message);
            }
            result = narrowed.result;
            narrowedBy = "elicitation";
          }
          // decline はそのまま続行（絞り込まないという回答）
        }
      }

      // ④ 要約を依頼する（sampling）／使えないなら抜粋を返す
      let summary: string;
      let summarySource: "sampling" | "excerpt";
      let model: string | undefined;
      let skipReason: SkipReason | undefined;

      if (!support.sampling) {
        degraded.sampling = true;
        skipReason = "unsupported";
        summary = buildExcerptDigest(result, skipReason);
        summarySource = "excerpt";
      } else {
        const excerpts = collectExcerpts(repository, result);
        const asked = await requestSummary(
          server,
          { promptText: buildSummaryPromptText(query, result, excerpts), mode: summaryMode },
          callContext,
        );
        if (asked.ok) {
          summary = asked.text;
          summarySource = "sampling";
          model = asked.model;
        } else {
          degraded.sampling = true;
          skipReason = asked.reason;
          summary = buildExcerptDigest(result, skipReason);
          summarySource = "excerpt";
        }
      }

      const notes = [
        `対象: ${describeScope(scope)}（${scope.source === "roots" ? "roots で絞り込み" : "サーバー設定"}）`,
        `絞り込み: ${narrowedBy}`,
        summarySource === "sampling"
          ? `要約: クライアントの LLM で生成（model=${model}）`
          : "要約: 未生成（抜粋を返しました）",
      ].join(" / ");

      return {
        content: [
          { type: "text" as const, text: `${summary}\n\n---\n${notes}` },
          // 本文は渡さず参照だけ返す（中間プロジェクト1 と同じ方針）
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
          mode: summaryMode,
          scopeSource: scope.source,
          scopeDirectories: scope.directories.includes("") ? [] : [...scope.directories],
          narrowedBy,
          ...(result.directory === undefined ? {} : { narrowedTo: result.directory }),
          totalMatched: result.totalMatched,
          returned: result.returned,
          truncated: result.truncated,
          summary,
          summarySource,
          ...(model === undefined ? {} : { model }),
          ...(skipReason === undefined ? {} : { skipReason }),
          degraded,
          results: result.hits.map((hit) => ({
            path: hit.path,
            uri: hit.uri,
            title: hit.title,
            score: hit.score,
            snippet: hit.snippet,
          })),
        },
      };
    },
  );
}

/** ツール実行の失敗。JSON-RPC エラーではなく isError で返す（セッション5） */
function toolError(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}
