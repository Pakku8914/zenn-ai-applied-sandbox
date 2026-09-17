/**
 * 本章のレビュー対象 ―― 社内申請ワークフロー MCP サーバー（リリース候補）
 *
 * ツール 3 本＋プロンプト 1 本。リソースは登録していません
 * （＝ resources 系メソッドは「宣言していないケイパビリティ」になります。問題4 で使います）。
 *
 * sanitize: false は「対策を外すと何が起きるか」を再現するためのスイッチです。
 * 既定は true で、本番でこのスイッチを false にすることはありません。
 */
import { createHmac, randomBytes } from "node:crypto";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import { createStore, decideRequest, getRequest, searchRequests } from "./approval-lite.js";
import { createBoundary, sanitizeExternalText, wrapUntrusted } from "./guard-lite.js";

export const SCOPES = ["requests:read", "requests:approve"] as const;
export type Scope = (typeof SCOPES)[number];

export const SERVER_NAME = "review05-approval-gate";
export const SERVER_VERSION = "0.1.0";
export const MAX_LIMIT = 10;

export type GateServerOptions = {
  /** このセッションのトークンに付与されたスコープ（既定は読み取りのみ） */
  readonly scopes?: readonly Scope[];
  /** false にすると get_request の出口を素通しにする（欠陥の再現用） */
  readonly sanitize?: boolean;
  /** 監査ログの行を受け取る。既定は stderr（stdout は JSON-RPC の通信路なので使わない） */
  readonly audit?: (line: string) => void;
  /** 境界の nonce。テストでは固定値を注入する */
  readonly nonce?: () => string;
  /** 参照値（HMAC）の鍵。本番は環境変数やシークレットマネージャから読む */
  readonly pepper?: string;
};

export function createGateServer(options: GateServerOptions = {}): McpServer {
  const scopes = new Set<Scope>(options.scopes ?? ["requests:read"]);
  const sanitize = options.sanitize ?? true;
  const nonce = options.nonce ?? (() => randomBytes(8).toString("hex"));
  const pepper = options.pepper ?? "review05-dev-pepper";
  const audit =
    options.audit ??
    ((line: string) => {
      process.stderr.write(`${line}\n`);
    });

  const store = createStore();
  const server = new McpServer({ name: SERVER_NAME, version: SERVER_VERSION });

  /** 生値の代わりに載せる参照値。同じ入力なら同じ値になるので追跡できる */
  const ref = (value: string): string =>
    createHmac("sha256", pepper).update(value).digest("hex").slice(0, 16);

  const log = (record: Record<string, unknown>): void => {
    audit(JSON.stringify({ ts: new Date().toISOString(), server: SERVER_NAME, ...record }));
  };

  const denyScope = (required: Scope, target: string) => {
    log({ event: "tool_call", target, outcome: "rejected", reason: "forbidden" });
    return {
      content: [
        {
          type: "text" as const,
          text:
            `この操作には ${required} スコープが必要ですが、現在のトークンには付与されていません。` +
            "管理者に権限の付与を依頼してから呼び直してください（同じトークンで再試行しても結果は変わりません）。",
        },
      ],
      isError: true,
    };
  };

  server.registerTool(
    "search_requests",
    {
      title: "申請の検索",
      description:
        "社内申請を条件で絞り込み、一覧の要約を返します。申請の本文（申請理由）は返しません。" +
        "1 件の中身を読みたいときはこのツールを使わず get_request を使ってください。",
      inputSchema: {
        query: z
          .string()
          .min(1)
          .max(40)
          .optional()
          .describe("検索語（件名と本文の部分一致）。省略すると全件が対象です"),
        status: z
          .enum(["submitted", "approved", "rejected"])
          .optional()
          .describe("状態で絞り込みます。省略すると全状態が対象です"),
        limit: z
          .number()
          .int()
          .min(1)
          .max(MAX_LIMIT)
          .default(3)
          .describe(`返す件数の上限（1〜${MAX_LIMIT}、既定 3）`),
      },
      outputSchema: {
        total: z.number().int(),
        returned: z.number().int(),
        truncated: z.boolean(),
        items: z.array(
          z.object({
            id: z.string(),
            title: z.string(),
            status: z.string(),
            amountYen: z.number().int(),
          }),
        ),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    ({ query, status, limit }) => {
      if (!scopes.has("requests:read")) return denyScope("requests:read", "search_requests");

      const found = searchRequests(store, { query, status, limit });
      const truncated = found.total > found.items.length;
      log({
        event: "tool_call",
        target: "search_requests",
        outcome: "ok",
        params: {
          queryLength: query?.length ?? 0,
          queryRef: query === undefined ? "-" : ref(query),
          statusSpecified: status !== undefined,
          limit,
        },
        resultCount: found.items.length,
      });

      return {
        content: [
          {
            type: "text" as const,
            text: [
              `${found.total} 件が一致し、${found.items.length} 件を返します。`,
              ...found.items.map(
                (item) => `- ${item.id} ${item.title}（${item.status} / ${item.amountYen} 円）`,
              ),
              ...(truncated
                ? ["（上限に達しました。limit を上げるか status で絞り込んでから呼び直してください）"]
                : []),
            ].join("\n"),
          },
        ],
        structuredContent: {
          total: found.total,
          returned: found.items.length,
          truncated,
          items: found.items,
        },
      };
    },
  );

  server.registerTool(
    "get_request",
    {
      title: "申請の詳細取得",
      description:
        "申請 1 件の詳細と本文を返します。複数件を探したいときはこのツールを使わず search_requests を使ってください。",
      inputSchema: {
        id: z
          .string()
          .regex(/^req-\d{4}$/)
          .describe("申請ID（例: req-1001）"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    ({ id }) => {
      if (!scopes.has("requests:read")) return denyScope("requests:read", "get_request");

      const row = getRequest(store, id);
      if (row === undefined) {
        log({
          event: "tool_call",
          target: "get_request",
          outcome: "rejected",
          reason: "not_found",
          params: { idRef: ref(id) },
        });
        return {
          content: [
            {
              type: "text" as const,
              text:
                "指定された申請が見つかりません。search_requests で存在する申請IDを確認してから呼び直してください" +
                "（同じIDで再試行しても結果は変わりません）。",
            },
          ],
          isError: true,
        };
      }

      const header = `${row.id} ${row.title}（状態 ${row.status} / ${row.amountYen} 円 / 申請者 ${row.applicantId}）`;

      if (!sanitize) {
        // ★ 欠陥の再現用。外部データを素通しし、境界も付けない
        log({
          event: "tool_call",
          target: "get_request",
          outcome: "ok",
          params: { idRef: ref(id) },
        });
        return { content: [{ type: "text" as const, text: `${header}\n申請理由:\n${row.body}` }] };
      }

      const report = sanitizeExternalText(row.body);
      const boundary = createBoundary(nonce());
      log({
        event: "tool_call",
        target: "get_request",
        outcome: "ok",
        params: { idRef: ref(id), truncated: report.truncated },
        findings: report.findings.map((finding) => finding.id),
      });
      return {
        content: [
          {
            type: "text" as const,
            text: [
              header,
              wrapUntrusted(boundary, `申請 ${row.id} の本文（申請者の自由記述）`, report.text),
            ].join("\n"),
          },
        ],
      };
    },
  );

  server.registerTool(
    "decide_request",
    {
      title: "申請の承認・却下",
      description:
        "申請を承認または却下します。既定はドライランで、確定するには同じ引数に confirm: true を付けて呼び直します。" +
        "状態を変えずに内容だけ知りたいときはこのツールを使わず get_request を使ってください。",
      inputSchema: {
        id: z
          .string()
          .regex(/^req-\d{4}$/)
          .describe("申請ID（例: req-1001）"),
        decision: z
          .enum(["approve", "reject"])
          .describe("approve なら承認、reject なら却下します"),
        confirm: z
          .boolean()
          .default(false)
          .describe("false（既定）ならドライラン。実際に確定するときだけ true にします"),
      },
      outputSchema: {
        applied: z.boolean(),
        id: z.string(),
        decision: z.string(),
        status: z.string(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    ({ id, decision, confirm }) => {
      if (!scopes.has("requests:approve")) return denyScope("requests:approve", "decide_request");

      const row = getRequest(store, id);
      if (row === undefined) {
        log({
          event: "tool_call",
          target: "decide_request",
          outcome: "rejected",
          reason: "not_found",
          params: { idRef: ref(id) },
        });
        return {
          content: [
            {
              type: "text" as const,
              text:
                "指定された申請が見つかりません。search_requests で存在する申請IDを確認してから呼び直してください" +
                "（同じIDで再試行しても結果は変わりません）。",
            },
          ],
          isError: true,
        };
      }

      if (row.status !== "submitted") {
        log({
          event: "tool_call",
          target: "decide_request",
          outcome: "rejected",
          reason: "not_decidable",
          params: { idRef: ref(id) },
        });
        return {
          content: [
            {
              type: "text" as const,
              text:
                `この申請は既に ${row.status} のため決裁できません。決裁できるのは submitted の申請だけです。` +
                "search_requests に status: \"submitted\" を指定して対象を選び直してください。",
            },
          ],
          isError: true,
        };
      }

      if (!confirm) {
        log({
          event: "tool_call",
          target: "decide_request",
          outcome: "ok",
          params: { idRef: ref(id), decision, confirm: false },
        });
        const label = decision === "approve" ? "承認" : "却下";
        return {
          content: [
            {
              type: "text" as const,
              text:
                `[ドライラン] ${row.id}「${row.title}」を${label}します。まだ確定していません。` +
                "確定するには同じ引数に confirm: true を付けて呼び直してください。",
            },
          ],
          structuredContent: {
            applied: false,
            id: row.id,
            decision,
            status: row.status,
          },
        };
      }

      const outcome = decideRequest(store, id, decision);
      if (!outcome.ok) {
        // ここに来るのは並行更新など想定外の場合だけ。内部の詳細は返さない
        log({
          event: "tool_call",
          target: "decide_request",
          outcome: "error",
          reason: outcome.reason,
          params: { idRef: ref(id) },
        });
        return {
          content: [
            { type: "text" as const, text: "決裁に失敗しました。時間をおいて再試行してください。" },
          ],
          isError: true,
        };
      }

      log({
        event: "tool_call",
        target: "decide_request",
        outcome: "ok",
        params: { idRef: ref(id), decision, confirm: true },
      });
      return {
        content: [
          { type: "text" as const, text: `${row.id} を ${outcome.status} にしました。` },
        ],
        structuredContent: { applied: true, id: row.id, decision, status: outcome.status },
      };
    },
  );

  server.registerPrompt(
    "draft_reply",
    {
      title: "申請への返信の下書き",
      description: "指定した申請の内容をもとに、申請者へ返す文面の下書きを組み立てます。",
      argsSchema: {
        id: z.string().describe("申請ID（例: req-1001）"),
      },
    },
    ({ id }) => {
      const row = getRequest(store, id);
      if (row === undefined) {
        // プロンプトの失敗は JSON-RPC エラー（isError はツール専用の仕組み）
        throw new McpError(
          ErrorCode.InvalidParams,
          "指定された申請が見つかりません。search_requests で確認してください。",
        );
      }
      const report = sanitizeExternalText(row.body);
      const boundary = createBoundary(nonce());
      return {
        messages: [
          {
            role: "user" as const,
            content: {
              type: "text" as const,
              text: [
                "次の申請への返信文を 3 行以内で下書きしてください。",
                `申請: ${row.id} ${row.title}（状態 ${row.status}）`,
                wrapUntrusted(boundary, `申請 ${row.id} の本文（申請者の自由記述）`, report.text),
              ].join("\n"),
            },
          },
        ],
      };
    },
  );

  return server;
}
