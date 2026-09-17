/**
 * 問題5 の解答：購読可能リソースを 2 つにし、3 種類の通知を送り分ける
 *
 * 通知の判断
 *   ① 用語を追加した   → glossary://index の「中身」が変わる → updated（購読者にだけ）
 *   ② 用語を追加した   → glossary://{term} は list を持たないので resources/list は変わらない
 *                        → list_changed は送らない（送ると無意味な list 取り直しを起こす）
 *   ③ ツールを無効化した → tools/list が変わる → tools/list_changed（SDK が自動で送る）
 */
import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import {
  ErrorCode,
  McpError,
  SubscribeRequestSchema,
  UnsubscribeRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import {
  TERM_SLUG_PATTERN,
  addWorkLog,
  findMember,
  findProject,
  getDashboardSnapshot,
  glossary,
  renderTermMarkdown,
  type GlossaryEntry,
} from "../data.js";

const SUMMARY_URI = "dashboard://summary/current";
const INDEX_URI = "glossary://index";
const SUBSCRIBABLE_URIS = new Set<string>([SUMMARY_URI, INDEX_URI]);

export function createDashboardServerQ5(): McpServer {
  const server = new McpServer(
    { name: "team-dashboard-q5", version: "0.3.0" },
    { capabilities: { resources: { subscribe: true, listChanged: true } } },
  );

  // 購読中の URI 集合。stdio は 1 プロセス = 1 接続なのでこれで足ります。
  // HTTP で 1 プロセスが複数セッションを持つ場合はセッション単位に持つ必要があります（セッション7）。
  const subscribedUris = new Set<string>();

  // data.ts の glossary は readonly なので、追加できるコピーを持つ
  const terms: GlossaryEntry[] = [...glossary];

  registerResources(server, terms);
  registerSubscriptionHandlers(server, subscribedUris);
  registerTools(server, terms, subscribedUris);

  return server;
}

function registerResources(server: McpServer, terms: GlossaryEntry[]): void {
  server.registerResource(
    "dashboard_summary",
    SUMMARY_URI,
    {
      title: "チーム稼働サマリー（最新）",
      description: "チーム全体の稼働時間の集計結果です。購読すると更新通知を受け取れます。",
      mimeType: "application/json",
    },
    async (uri) => ({
      contents: [
        {
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify(getDashboardSnapshot(), null, 2),
        },
      ],
    }),
  );

  server.registerResource(
    "glossary_index",
    INDEX_URI,
    {
      title: "社内用語辞書の索引",
      description:
        "登録されている用語の一覧を Markdown の表で返します。" +
        "用語が追加されると内容が変わるため、購読に対応しています。",
      mimeType: "text/markdown",
    },
    async (uri) => ({
      contents: [{ uri: uri.href, mimeType: "text/markdown", text: renderIndex(terms) }],
    }),
  );

  server.registerResource(
    "glossary_term",
    // list を持たせない → 用語が増えても resources/list は変わらない
    new ResourceTemplate("glossary://{term}", {
      list: undefined,
      complete: { term: (value) => completeSlugs(terms, value) },
    }),
    {
      title: "社内用語辞書",
      description: "社内用語 1 件の定義を Markdown で返します。",
      mimeType: "text/markdown",
    },
    async (_uri, variables) => {
      const raw = variables["term"];
      const slug = normalizeSlug(Array.isArray(raw) ? (raw[0] ?? "") : (raw ?? ""));
      const entry = slug === undefined ? undefined : terms.find((item) => item.slug === slug);
      if (entry === undefined) {
        throw new McpError(ErrorCode.InvalidParams, "指定された用語は辞書にありません。");
      }
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
}

function registerSubscriptionHandlers(server: McpServer, subscribedUris: Set<string>): void {
  server.server.setRequestHandler(SubscribeRequestSchema, async (request) => {
    const uri = request.params.uri;
    if (!SUBSCRIBABLE_URIS.has(uri)) {
      throw new McpError(
        ErrorCode.InvalidParams,
        `${uri} は購読に対応していません。購読できる URI: ${[...SUBSCRIBABLE_URIS].join(", ")}`,
      );
    }
    subscribedUris.add(uri);
    return {};
  });

  server.server.setRequestHandler(UnsubscribeRequestSchema, async (request) => {
    subscribedUris.delete(request.params.uri);
    return {};
  });
}

function registerTools(
  server: McpServer,
  terms: GlossaryEntry[],
  subscribedUris: Set<string>,
): void {
  server.registerTool(
    "add_glossary_term",
    {
      title: "用語の追加",
      description:
        "社内用語辞書に用語を 1 件追加します。追加すると索引リソース（glossary://index）の内容が変わります。" +
        "すでに同じスラッグが登録されている場合は失敗します。",
      inputSchema: {
        slug: z
          .string()
          .regex(TERM_SLUG_PATTERN, "英小文字・数字・ハイフンで 1〜32 文字にしてください")
          .describe("URI に載る識別子（例: burndown）。あとから変更できません"),
        term: z.string().min(1).max(40).describe("人間向けの表記（例: バーンダウン）"),
        category: z
          .enum(["開発プロセス", "指標", "稼働管理", "運用", "目標管理"])
          .describe("分類。既存の用語と同じ語彙から選びます"),
        definition: z.string().min(5).max(200).describe("定義（5〜200 文字）"),
      },
      outputSchema: {
        slug: z.string().describe("登録したスラッグ"),
        termCount: z.number().int().describe("登録後の用語件数"),
        notified: z.boolean().describe("索引リソースの購読者に更新通知を送ったか"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false, // 既存の用語を書き換えない
        idempotentHint: false, // 2 回目は失敗するので「追加の効果がない」とは言えない
        openWorldHint: false,
      },
    },
    async ({ slug, term, category, definition }) => {
      if (slug === "index") {
        return toolError("slug に index は使えません（glossary://index と URI が衝突します）。");
      }
      if (terms.some((entry) => entry.slug === slug)) {
        return toolError(`スラッグ ${slug} はすでに登録されています。別の名前を指定してください。`);
      }

      terms.push({ slug, term, category, definition, related: [] });
      terms.sort((a, b) => a.slug.localeCompare(b.slug));

      // 索引（glossary://index）の中身が変わったので、購読者にだけ通知する
      const notified = subscribedUris.has(INDEX_URI);
      if (notified) {
        await server.server.sendResourceUpdated({ uri: INDEX_URI });
      }
      // glossary://{term} は list を持たないため resources/list は変わらない → list_changed は送らない

      return {
        content: [
          {
            type: "text",
            text: `用語 ${term}（${slug}）を追加しました。登録数は ${terms.length} 件です。`,
          },
        ],
        structuredContent: { slug, termCount: terms.length, notified },
      };
    },
  );

  // disable() を呼ぶために戻り値を保持する
  const workLogTool = server.registerTool(
    "add_work_log",
    {
      title: "稼働記録の追加",
      description: "稼働記録を 1 件追加します。集計リソースの内容が変わります。",
      inputSchema: {
        memberId: z.string().regex(/^m-\d{3}$/).describe("メンバー ID（例: m-003）"),
        projectId: z.string().regex(/^p-[a-z-]{2,32}$/).describe("プロジェクト ID（例: p-report）"),
        date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe("稼働日（YYYY-MM-DD）"),
        hours: z.number().min(0.5).max(12).describe("稼働時間（0.5〜12 時間）"),
      },
      outputSchema: {
        revision: z.number().int().describe("更新後の改訂番号"),
        notified: z.boolean().describe("集計リソースの購読者に更新通知を送ったか"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ memberId, projectId, date, hours }) => {
      if (findMember(memberId) === undefined || findProject(projectId) === undefined) {
        return toolError("memberId / projectId に存在しない ID が指定されています。");
      }
      const result = addWorkLog({ memberId, projectId, date, hours });
      const notified = subscribedUris.has(SUMMARY_URI);
      if (notified) {
        await server.server.sendResourceUpdated({ uri: SUMMARY_URI });
      }
      return {
        content: [{ type: "text", text: `稼働記録を追加しました（改訂 ${result.revision}）。` }],
        structuredContent: { revision: result.revision, notified },
      };
    },
  );

  server.registerTool(
    "set_maintenance_mode",
    {
      title: "メンテナンスモードの切り替え",
      description:
        "メンテナンス中は稼働記録の追加ツール（add_work_log）を一覧から外します。" +
        "切り替えるとツール一覧が変わるため、クライアントに tools/list_changed が通知されます。",
      inputSchema: {
        enabled: z.boolean().describe("true でメンテナンス開始（add_work_log を無効化）"),
      },
      outputSchema: {
        maintenance: z.boolean().describe("メンテナンス中かどうか"),
        addWorkLogEnabled: z.boolean().describe("add_work_log が有効かどうか"),
      },
      annotations: {
        readOnlyHint: false, // サーバーの応答（tools/list）が変わるので読み取り専用ではない
        destructiveHint: false, // データを壊さない
        idempotentHint: true, // 同じ値で 2 回呼んでも結果は同じ
        openWorldHint: false,
      },
    },
    async ({ enabled }) => {
      // disable() / enable() を呼ぶと SDK が notifications/tools/list_changed を送ります
      if (enabled) {
        workLogTool.disable();
      } else {
        workLogTool.enable();
      }
      return {
        content: [
          { type: "text", text: enabled ? "メンテナンスを開始しました。" : "メンテナンスを終了しました。" },
        ],
        structuredContent: { maintenance: enabled, addWorkLogEnabled: !enabled },
      };
    },
  );
}

function renderIndex(terms: readonly GlossaryEntry[]): string {
  const rows = terms.map((entry) => `| ${entry.slug} | ${entry.term} | ${entry.category} |`);
  return [
    `# 社内用語辞書（${terms.length} 件）`,
    "",
    "| スラッグ | 用語 | 分類 |",
    "| :--- | :--- | :--- |",
    ...rows,
  ].join("\n");
}

function completeSlugs(terms: readonly GlossaryEntry[], value: string): string[] {
  const needle = value.trim().toLowerCase();
  return terms
    .map((entry) => entry.slug)
    .filter((slug) => slug.startsWith(needle))
    .sort((a, b) => a.localeCompare(b));
}

function normalizeSlug(raw: string): string | undefined {
  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    return undefined;
  }
  return TERM_SLUG_PATTERN.test(decoded) ? decoded : undefined;
}

function toolError(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}
