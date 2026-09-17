/**
 * 社内申請ワークフロー MCP サーバー（Good 実装：意図ベースの 6 ツール）
 *
 * 18 本の REST エンドポイントを、ユーザーが下す 6 つの意思決定に対応させたものです。
 * トランスポートには接続しません（サンドボックスの create-server.ts と同じ方針）。
 * このサーバー定義はセッション11・最終プロジェクトの土台になります。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import {
  CATEGORIES,
  DECISIONS,
  STATUSES,
  addComment,
  applyDecision,
  applySubmit,
  createStore,
  formatDetailText,
  formatSummaryLine,
  getRequestDetail,
  previewDecision,
  previewSubmit,
  saveRequest,
  searchRequests,
  type Store,
} from "./data.js";

/**
 * ツールと必要スコープの対応。
 * 実際のトークン検証はセッション12（OAuth 2.1）で実装します。
 * ここで宣言しておくのは、「ツールを 1 本増やすとは、権限を 1 つ増やすこと」を
 * 設計時に見えるようにするためです。
 */
export const TOOL_SCOPES = {
  search_requests: "requests:read",
  get_request: "requests:read",
  save_request: "requests:write",
  submit_request: "requests:write",
  decide_request: "requests:approve",
  comment_on_request: "requests:write",
} as const;

export type ToolName = keyof typeof TOOL_SCOPES;

const REQUEST_ID = /^req-\d{4}$/;
const USER_ID = /^u-\d{3}$/;
/** 添付は URL で参照させる。https 以外を受け取らない（SSRF 対策の詳細はセッション15） */
const HTTPS_URL = /^https:\/\/[^\s]+$/;

/** registerTool の戻り値。enable() / disable() を持つハンドルです */
type RegisteredTool = ReturnType<McpServer["registerTool"]>;

export type WorkflowServer = {
  server: McpServer;
  store: Store;
  tools: Record<ToolName, RegisteredTool>;
};

/** ツール実行の失敗。3 層のエラーの使い分けは次章で作り込みます */
function toolError(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

export function createWorkflowServer(store: Store = createStore()): WorkflowServer {
  const server = new McpServer({ name: "workflow-requests", version: "1.0.0" });

  // ── 1. 探す（requests:read） ────────────────────────────────────────────
  const searchTool = server.registerTool(
    "search_requests",
    {
      title: "申請を探す",
      description:
        "申請を条件で絞り込み、要約の一覧を返します（本文は返しません）。" +
        "ID が既に分かっているときは get_request を使ってください。" +
        "結果が多いときは nextCursor を cursor に渡して続きを取得します。",
      inputSchema: {
        query: z
          .string()
          .min(1)
          .max(100)
          .optional()
          .describe("題名と本文に対するキーワード検索（部分一致）"),
        status: z
          .array(z.enum(STATUSES))
          .max(4)
          .optional()
          .describe("状態で絞り込む（複数指定可）。省略するとすべての状態を対象にします"),
        category: z.enum(CATEGORIES).optional().describe("申請区分。この 4 種類以外は存在しません"),
        applicantId: z
          .string()
          .regex(USER_ID)
          .optional()
          .describe("申請者のユーザー ID（u-001 の形式）"),
        minAmountYen: z
          .number()
          .int()
          .min(0)
          .optional()
          .describe("金額の下限（円）。この額以上の申請だけを返します"),
        limit: z.number().int().min(1).max(50).default(10).describe("返す件数（1〜50、既定は 10）"),
        cursor: z.string().optional().describe("前回の結果の nextCursor をそのまま渡します"),
      },
      outputSchema: {
        total: z.number().int().describe("条件に一致した総件数"),
        returned: z.number().int().describe("このレスポンスに含まれる件数"),
        hasMore: z.boolean().describe("続きがあるか"),
        nextCursor: z.string().optional().describe("続きを取得するためのカーソル"),
        items: z
          .array(
            z.object({
              id: z.string(),
              title: z.string(),
              // 出力側の状態・区分は文字列にしています。異常系でも同じ形を返せるようにするためです
              category: z.string(),
              status: z.string(),
              amountYen: z.number().int(),
              applicantName: z.string(),
              updatedAt: z.string(),
            }),
          )
          .describe("申請の要約。本文は含みません"),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ query, status, category, applicantId, minAmountYen, limit, cursor }) => {
      try {
        const result = searchRequests(store, {
          query,
          status,
          category,
          applicantId,
          minAmountYen,
          limit,
          cursor,
        });
        const header =
          `${result.total} 件中 ${result.returned} 件` +
          (result.hasMore ? "（続きがあります。cursor に nextCursor を渡してください）" : "");
        return {
          content: [{ type: "text", text: [header, ...result.items.map(formatSummaryLine)].join("\n") }],
          structuredContent: {
            total: result.total,
            returned: result.returned,
            hasMore: result.hasMore,
            ...(result.nextCursor === undefined ? {} : { nextCursor: result.nextCursor }),
            items: result.items,
          },
        };
      } catch (error) {
        // outputSchema を宣言したツールは、失敗時も同じ形を返せるようにしておきます
        return {
          content: [
            { type: "text", text: error instanceof Error ? error.message : "検索に失敗しました" },
          ],
          structuredContent: { total: 0, returned: 0, hasMore: false, items: [] },
          isError: true,
        };
      }
    },
  );

  // ── 2. 中身を把握する（requests:read） ─────────────────────────────────
  const getTool = server.registerTool(
    "get_request",
    {
      title: "申請の詳細を見る",
      description:
        "申請 1 件の詳細（題名・本文・金額・状態・承認ルートの進行状況）を返します。" +
        "ID が分からないときは先に search_requests で探してください。" +
        "コメント・添付・履歴は既定では返しません。判断に必要なものだけ include に並べてください。",
      inputSchema: {
        requestId: z.string().regex(REQUEST_ID).describe("申請 ID（req-1001 の形式）"),
        include: z
          .array(z.enum(["comments", "attachments", "history"]))
          .max(3)
          .optional()
          .describe("追加で含めるセクション。省略すると詳細と承認ルートだけを返します"),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ requestId, include }) => {
      const detail = getRequestDetail(store, requestId, include ?? []);
      if (detail === undefined) {
        return toolError(
          `申請 ${requestId} は見つかりません。search_requests で ID を確認してください。`,
        );
      }
      return { content: [{ type: "text", text: formatDetailText(detail) }] };
    },
  );

  // ── 3. 書く・書き直す（requests:write） ────────────────────────────────
  const saveTool = server.registerTool(
    "save_request",
    {
      title: "申請を書く（新規作成・下書き更新）",
      description:
        "申請の下書きを作成または更新します。requestId を省略すると新規作成、指定すると既存の下書きの更新です。" +
        "新規作成では title・category・amountYen・body が必須です。" +
        "このツールは審査を開始しません（提出は submit_request）。編集できるのは draft の申請だけです。",
      inputSchema: {
        requestId: z
          .string()
          .regex(REQUEST_ID)
          .optional()
          .describe("更新する下書きの ID。省略すると新規作成になります"),
        title: z.string().min(1).max(60).optional().describe("題名（60 文字以内）"),
        category: z.enum(CATEGORIES).optional().describe("申請区分"),
        amountYen: z
          .number()
          .int()
          .min(0)
          .max(10_000_000)
          .optional()
          .describe("金額（円、税込）。休暇など金額のない申請は 0"),
        body: z.string().min(1).max(2000).optional().describe("申請本文。理由と内訳を書きます"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ requestId, title, category, amountYen, body }) => {
      const outcome = saveRequest(store, { requestId, title, category, amountYen, body });
      if (!outcome.ok) return toolError(outcome.message);
      const request = outcome.request;
      const label = outcome.created ? "作成しました" : "更新しました";
      return {
        content: [
          {
            type: "text",
            text:
              `${request.id} を${label}（状態: ${request.status} / 金額: ${request.amountYen} 円）\n` +
              `承認ルート: ${request.approvals.map((s) => s.approverName).join(" → ")}\n` +
              "提出するには submit_request を使ってください。",
          },
        ],
      };
    },
  );

  // ── 4. 審査を始める（requests:write・二段階） ─────────────────────────
  const submitTool = server.registerTool(
    "submit_request",
    {
      title: "申請を提出する（確認つき）",
      description:
        "下書きの申請を提出し、承認ルートの審査を開始します。提出すると承認者に通知が飛び、取り消しは Web 画面でしかできません。" +
        "そのため二段階です。まず confirm を付けずに呼ぶと、提出後に何が起きるかの予告と previewToken を返します。" +
        "内容をユーザーに確認したうえで、confirm: true と previewToken を付けて再度呼ぶと確定します。",
      inputSchema: {
        requestId: z.string().regex(REQUEST_ID).describe("提出する下書きの ID"),
        confirm: z
          .boolean()
          .default(false)
          .describe("false（既定）はドライラン。true で実際に提出します（previewToken が必須）"),
        previewToken: z
          .string()
          .optional()
          .describe("ドライランの結果に含まれる値をそのまま渡します。申請が変わると無効になります"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ requestId, confirm, previewToken }) => {
      const preview = previewSubmit(store, requestId);
      if (!preview.ok) return toolError(preview.message);

      if (!confirm) {
        return {
          content: [
            {
              type: "text",
              text:
                `【ドライラン】${requestId} を提出すると次のようになります。\n` +
                `状態: ${preview.currentStatus} → ${preview.nextStatus}\n` +
                `通知先: ${preview.notifyTo.join(", ")}\n` +
                `確定するには confirm: true と previewToken: ${preview.previewToken} を付けて再度呼び出してください。`,
            },
          ],
        };
      }
      if (previewToken === undefined) {
        return toolError(
          "confirm: true で呼ぶときは previewToken が必要です。先に confirm を省略して呼び出し、返ってきた previewToken を渡してください。",
        );
      }
      if (previewToken !== preview.previewToken) {
        return toolError(
          "previewToken が一致しません。申請の内容が変わった可能性があります。もう一度 confirm を省略して呼び出し、内容を確認してから確定してください。",
        );
      }

      const applied = applySubmit(store, requestId);
      if (!applied.ok) return toolError(applied.message);
      return {
        content: [
          {
            type: "text",
            text: `${requestId} を提出しました（状態: ${applied.status} / 通知先: ${applied.notifyTo.join(", ")}）`,
          },
        ],
      };
    },
  );

  // ── 5. 決着をつける（requests:approve・二段階） ───────────────────────
  const decideTool = server.registerTool(
    "decide_request",
    {
      title: "申請を承認・却下・差し戻しする（確認つき）",
      description:
        "審査中の申請に決裁を下します。決裁は取り消せないため二段階です。" +
        "まず confirm を付けずに呼んで、何段目の決裁か・確定後の状態・通知先・previewToken を受け取り、" +
        "ユーザーの承諾を得てから confirm: true と previewToken を付けて再度呼び出してください。" +
        "reject と return_for_changes では comment（理由）が必須です。",
      inputSchema: {
        requestId: z.string().regex(REQUEST_ID).describe("決裁する申請の ID"),
        decision: z
          .enum(DECISIONS)
          .describe(
            "approve=承認（最終段なら承認確定）/ reject=却下（終了）/ return_for_changes=申請者へ差し戻して下書きに戻す",
          ),
        comment: z
          .string()
          .min(1)
          .max(500)
          .optional()
          .describe("決裁理由。reject と return_for_changes では必須。申請者に表示されます"),
        confirm: z
          .boolean()
          .default(false)
          .describe("false（既定）はドライラン。true で実際に決裁します（previewToken が必須）"),
        previewToken: z
          .string()
          .optional()
          .describe("ドライランの結果に含まれる値をそのまま渡します。申請が変わると無効になります"),
      },
      outputSchema: {
        applied: z.boolean().describe("実際に決裁したか（ドライランなら false）"),
        requestId: z.string(),
        decision: z.string(),
        currentStatus: z.string().describe("現在の状態"),
        nextStatus: z.string().describe("確定後の状態（ドライランでは見込み）"),
        stepLabel: z.string().describe("何段目の決裁か（例: 1/2 段目）"),
        finalizes: z.boolean().describe("この決裁で審査が終わるか"),
        notifyTo: z.array(z.string()).describe("通知先"),
        previewToken: z.string().optional().describe("確定時に渡す値（ドライランのときだけ返す）"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ requestId, decision, comment, confirm, previewToken }) => {
      const preview = previewDecision(store, requestId, decision, comment);
      if (!preview.ok) {
        return {
          content: [{ type: "text", text: preview.message }],
          structuredContent: {
            applied: false,
            requestId,
            decision,
            currentStatus: store.requests.get(requestId)?.status ?? "unknown",
            nextStatus: "unknown",
            stepLabel: "-",
            finalizes: false,
            notifyTo: [],
          },
          isError: true,
        };
      }

      const base = {
        requestId,
        decision,
        currentStatus: preview.currentStatus,
        nextStatus: preview.nextStatus,
        stepLabel: preview.stepLabel,
        finalizes: preview.finalizes,
        notifyTo: preview.notifyTo,
      };

      if (!confirm) {
        return {
          content: [
            {
              type: "text",
              text:
                `【ドライラン】${requestId} を ${decision} すると次のようになります。\n` +
                `${preview.stepLabel}（この決裁で審査が終わるか: ${preview.finalizes ? "はい" : "いいえ"}）\n` +
                `状態: ${preview.currentStatus} → ${preview.nextStatus}\n` +
                `通知先: ${preview.notifyTo.join(", ")}\n` +
                `確定するには confirm: true と previewToken: ${preview.previewToken} を付けて再度呼び出してください。`,
            },
          ],
          structuredContent: { applied: false, ...base, previewToken: preview.previewToken },
        };
      }
      if (previewToken === undefined || previewToken !== preview.previewToken) {
        const reason =
          previewToken === undefined
            ? "confirm: true で呼ぶときは previewToken が必要です。"
            : "previewToken が一致しません。申請の内容か決裁内容が変わっています。";
        return {
          content: [
            {
              type: "text",
              text: `${reason}confirm を省略して呼び出し、内容を確認してから確定してください。`,
            },
          ],
          structuredContent: { applied: false, ...base },
          isError: true,
        };
      }

      const applied = applyDecision(store, requestId, decision, comment);
      if (!applied.ok) {
        return {
          content: [{ type: "text", text: applied.message }],
          structuredContent: { applied: false, ...base },
          isError: true,
        };
      }
      return {
        content: [
          {
            type: "text",
            text:
              `${requestId} を ${decision} しました（${applied.stepLabel} / 状態: ${applied.status}）\n` +
              (applied.finalizes ? "審査は終了しました。" : `次の承認者: ${preview.notifyTo.join(", ")}`),
          },
        ],
        structuredContent: { applied: true, ...base, nextStatus: applied.status },
      };
    },
  );

  // ── 6. 補足を残す（requests:write） ────────────────────────────────────
  const commentTool = server.registerTool(
    "comment_on_request",
    {
      title: "申請にコメントを付ける",
      description:
        "申請にコメントを 1 件追加します。状態は変わりません。" +
        "決裁の理由を書きたい場合は decide_request の comment を使ってください（決裁と紐づいた記録になります）。" +
        "資料を添えたいときは共有リンクの URL を links に渡します（ファイル本体はアップロードできません）。",
      inputSchema: {
        requestId: z.string().regex(REQUEST_ID).describe("コメントを付ける申請の ID"),
        body: z.string().min(1).max(500).describe("コメント本文（500 文字以内）"),
        links: z
          .array(z.string().regex(HTTPS_URL))
          .max(3)
          .optional()
          .describe("参考資料の URL（https のみ、3 件まで）"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ requestId, body, links }) => {
      const result = addComment(store, requestId, body, links ?? []);
      if (!result.ok) return toolError(result.message);
      return {
        content: [
          {
            type: "text",
            text: `${requestId} にコメント ${result.commentId} を追加しました（合計 ${result.total} 件）`,
          },
        ],
      };
    },
  );

  return {
    server,
    store,
    tools: {
      search_requests: searchTool,
      get_request: getTool,
      save_request: saveTool,
      submit_request: submitTool,
      decide_request: decideTool,
      comment_on_request: commentTool,
    },
  };
}
