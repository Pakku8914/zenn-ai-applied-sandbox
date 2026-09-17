/**
 * 社内申請ワークフロー MCP サーバー（セッション11：エラー設計とトークン効率）
 *
 * セッション10 の good-create-server.ts（意図ベースの 6 ツール）を土台に、
 *   ① 失敗を 3 層に振り分ける
 *   ② AI が回復できる文面と、機械が読める error オブジェクトを返す
 *   ③ 返す情報量に上限を持たせ、上限に達したことを伝える
 * を入れたものです。ツール名・引数の形は前章から変えていません。
 *
 * トランスポートには接続しません（サンドボックスの create-server.ts と同じ方針）。
 * サーバープロセス側のコードなので stdout には一切書きません。
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
  encodeCursor,
  formatSummaryLine,
  previewDecision,
  previewSubmit,
  saveRequest,
  searchRequests,
  type Status,
  type Store,
  type WorkflowRequest,
} from "../session10/data.js";
import {
  internalFailure,
  quoteArg,
  toolFailure,
  toolFailureWith,
  type ToolFailure,
} from "./errors.js";
import { createBudgetApi, createBulkyStore, type BudgetApi } from "./fixtures.js";
import { BUDGET, bodyLink, fitLines, formatDetail } from "./respond.js";

/** ツールと必要スコープの対応（トークン検証の実装はセッション12） */
export const TOOL_SCOPES = {
  search_requests: "requests:read",
  get_request: "requests:read",
  save_request: "requests:write",
  submit_request: "requests:write",
  decide_request: "requests:approve",
  comment_on_request: "requests:write",
} as const;

export type ToolName = keyof typeof TOOL_SCOPES;

export const ALL_SCOPES: readonly string[] = [
  "requests:read",
  "requests:write",
  "requests:approve",
];

const REQUEST_ID = /^req-\d{4}$/;
const USER_ID = /^u-\d{3}$/;
/** 添付は URL で参照させる。https 以外を受け取らない（SSRF 対策の詳細はセッション15） */
const HTTPS_URL = /^https:\/\/[^\s]+$/;

/** 検索が失敗したときでも outputSchema の形を保つための空の値 */
const EMPTY_SEARCH = { total: 0, returned: 0, hasMore: false, items: [] } as const;

export type WorkflowServerOptions = {
  store?: Store;
  /** この接続に与えられた権限。既定は全部（実際の検証はセッション12） */
  grantedScopes?: readonly string[];
  /** 外部の予算照会 API。障害を注入したテストのために差し替えられる */
  budgetApi?: BudgetApi;
};

export type WorkflowServer = { server: McpServer; store: Store };

/** 状態に応じて「次に何をすればよいか」を返す。エラー文の説得力はここで決まる */
function nextActionFor(status: Status): string {
  switch (status) {
    case "draft":
      return "提出するには submit_request、内容を直すには save_request を使ってください。";
    case "in_review":
      return "決裁するには decide_request（confirm を省略してドライラン）を使ってください。";
    case "approved":
      return "この申請は承認済みで、これ以上の変更はできません。";
    case "rejected":
      return "この申請は却下済みです。作り直す場合は save_request で新しく起票してください。";
  }
}

/**
 * 対象の存在と状態を検査して、失敗なら分類つきで返す。
 *
 * 本来この分類はデータ層（data.ts）が持つべきものです。前章の data.ts は
 * message 文字列だけを返す作りなので、ここで補っています。
 * 最終プロジェクトではデータ層が code を返す形にします。
 */
function classify(
  store: Store,
  requestId: string,
  allowed: readonly Status[],
): ToolFailure | undefined {
  const request = store.requests.get(requestId);
  if (request === undefined) {
    return {
      code: "not_found",
      what: `申請 ${requestId} は見つかりません。`,
      next: "ID の形式は req-1001 です。search_requests で題名や申請者から探して、返ってきた id を使ってください。",
      retryable: false,
    };
  }
  if (!allowed.includes(request.status)) {
    return {
      code: "invalid_state",
      what: `申請 ${requestId} は現在 ${request.status} です。`,
      next: `この操作ができるのは ${allowed.join(" / ")} の申請だけです。${nextActionFor(request.status)}`,
      retryable: false,
    };
  }
  return undefined;
}

/** 権限の検査。stdio 構成では「プロセスの中で判定する」しかない（判断表の 2 行目） */
function scopeGuard(granted: readonly string[], tool: ToolName): ToolFailure | undefined {
  const required = TOOL_SCOPES[tool];
  if (granted.includes(required)) return undefined;
  return {
    code: "forbidden",
    what: `この操作には権限 ${required} が必要ですが、現在の接続には付与されていません。`,
    next:
      `付与されている権限は ${granted.length === 0 ? "なし" : granted.join(", ")} です。` +
      "権限が必要な操作はユーザーに依頼してください。状況の確認だけなら get_request が使えます。",
    retryable: false,
  };
}

export function createWorkflowServer(options: WorkflowServerOptions = {}): WorkflowServer {
  const store = options.store ?? createBulkyStore();
  const granted = options.grantedScopes ?? ALL_SCOPES;
  const budgetApi = options.budgetApi ?? createBudgetApi();
  const server = new McpServer({ name: "workflow-requests", version: "1.1.0" });

  // ── 1. 探す（requests:read） ────────────────────────────────────────────
  server.registerTool(
    "search_requests",
    {
      title: "申請を探す",
      description:
        "申請を条件で絞り込み、要約の一覧を返します（本文は返しません）。" +
        "ID が既に分かっているときは get_request を使ってください。" +
        `返す量には上限（${BUDGET.listChars} 文字）があり、超えた分は省略して件数を伝えます。` +
        "続きは nextCursor を cursor に渡して取得します。",
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
        hasMore: z.boolean().describe("続きがあるか（上限で切った場合も true）"),
        nextCursor: z.string().optional().describe("続きを取得するためのカーソル"),
        omitted: z
          .number()
          .int()
          .optional()
          .describe("返却上限のために省略した件数。0 件のときは返しません"),
        items: z
          .array(
            z.object({
              id: z.string(),
              title: z.string(),
              category: z.string(),
              status: z.string(),
              amountYen: z.number().int(),
              applicantName: z.string(),
              updatedAt: z.string(),
            }),
          )
          .describe("申請の要約。本文は含みません"),
        error: z
          .object({
            code: z.string(),
            retryable: z.boolean(),
            retryAfterSeconds: z.number().int().optional(),
          })
          .optional()
          .describe("失敗したときだけ返る機械可読なエラー"),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ query, status, category, applicantId, minAmountYen, limit, cursor }) => {
      const denied = scopeGuard(granted, "search_requests");
      if (denied !== undefined) return toolFailureWith(denied, EMPTY_SEARCH);

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

        const fitted = fitLines(
          result.items.map(formatSummaryLine),
          BUDGET.listChars,
          "cursor に nextCursor を渡すと続きが取れます。条件を足して絞り込むほうが確実です",
        );

        // 上限で切った場合も「続きがある」として扱い、続きの取り方まで返す
        const truncated = fitted.omitted > 0;
        const lastIncluded = result.items[fitted.included - 1];
        const hasMore = result.hasMore || truncated;
        const nextCursor =
          truncated && lastIncluded !== undefined
            ? encodeCursor(lastIncluded.id)
            : result.nextCursor;

        const header =
          `${result.total} 件中 ${fitted.included} 件を返しました` +
          (hasMore ? "（続きがあります）" : "");

        return {
          content: [{ type: "text", text: [header, fitted.text].join("\n") }],
          structuredContent: {
            total: result.total,
            returned: fitted.included,
            hasMore,
            ...(nextCursor === undefined ? {} : { nextCursor }),
            ...(truncated ? { omitted: fitted.omitted } : {}),
            items: result.items.slice(0, fitted.included),
          },
        };
      } catch (error) {
        // 例外の中身は「分類」にだけ使い、返す文面は自分で書く
        const failure: ToolFailure = String(error).includes("cursor")
          ? {
              code: "invalid_argument",
              what: "cursor の値を解釈できませんでした。",
              next: "cursor を省略して最初のページから取得し直してください。cursor は前回の結果の nextCursor をそのまま渡す値です。",
              retryable: false,
            }
          : internalFailure("search_requests", error);
        return toolFailureWith(failure, EMPTY_SEARCH);
      }
    },
  );

  // ── 2. 中身を把握する（requests:read） ─────────────────────────────────
  server.registerTool(
    "get_request",
    {
      title: "申請の詳細を見る",
      description:
        "申請 1 件の詳細（題名・本文・金額・状態・承認ルートの進行状況）を返します。" +
        "ID が分からないときは先に search_requests で探してください。" +
        `コメント・添付・履歴は既定では返しません。判断に必要なものだけ include に並べてください（各セクションは直近 ${BUDGET.sectionItems} 件まで）。` +
        `本文が ${BUDGET.bodyChars} 文字を超える場合は先頭だけを返し、全文の参照を添えます。`,
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
      const denied = scopeGuard(granted, "get_request");
      if (denied !== undefined) return toolFailure(denied);

      // 状態は問わない（どの状態でも中身は見せてよい）
      const failure = classify(store, requestId, STATUSES);
      if (failure !== undefined) return toolFailure(failure);

      const request = store.requests.get(requestId) as WorkflowRequest;
      const blocks: Array<
        | { type: "text"; text: string }
        | {
            type: "resource_link";
            uri: string;
            name: string;
            title: string;
            mimeType: string;
            description: string;
          }
      > = [{ type: "text", text: formatDetail(request, include ?? []) }];

      if (request.body.length > BUDGET.bodyChars) blocks.push(bodyLink(request));

      return { content: blocks };
    },
  );

  // ── 3. 書く・書き直す（requests:write） ────────────────────────────────
  server.registerTool(
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
      const denied = scopeGuard(granted, "save_request");
      if (denied !== undefined) return toolFailure(denied);

      if (requestId === undefined) {
        // 条件付き必須は JSON Schema で表現しづらいので、回復できるエラーで補う（前章の方針）
        const provided = { title, category, amountYen, body };
        const missing = (["title", "category", "amountYen", "body"] as const).filter(
          (key) => provided[key] === undefined,
        );
        if (missing.length > 0) {
          return toolFailure({
            code: "invalid_argument",
            what: `新規作成に必要な引数が足りません（不足: ${missing.join(", ")}）。`,
            next: "不足している引数を付けて呼び直してください。既存の下書きを更新したいのであれば requestId を指定してください。",
            retryable: false,
          });
        }
      } else {
        const failure = classify(store, requestId, ["draft"]);
        if (failure !== undefined) return toolFailure(failure);
      }

      const outcome = saveRequest(store, { requestId, title, category, amountYen, body });
      if (!outcome.ok) {
        // 前段の分類で拾いきれていない失敗。分類漏れなので内部エラーとして記録する
        return toolFailure(internalFailure("save_request", new Error(outcome.message)));
      }

      const request = outcome.request;
      return {
        content: [
          {
            type: "text",
            text:
              `${request.id} を${outcome.created ? "作成" : "更新"}しました（状態: ${request.status} / 金額: ${request.amountYen} 円）\n` +
              `承認ルート: ${request.approvals.map((step) => step.approverName).join(" → ")}\n` +
              "提出するには submit_request を使ってください（提出後は取り消せません）。",
          },
        ],
      };
    },
  );

  // ── 4. 審査を始める（requests:write・二段階・外部依存あり） ────────────
  server.registerTool(
    "submit_request",
    {
      title: "申請を提出する（確認つき）",
      description:
        "下書きの申請を提出し、承認ルートの審査を開始します。提出すると承認者に通知が飛び、取り消しは Web 画面でしかできません。" +
        "そのため二段階です。confirm を付けずに呼ぶと、提出後に何が起きるかの予告と previewToken を返します。" +
        "内容をユーザーに確認したうえで、confirm: true と previewToken を付けて再度呼ぶと確定します。" +
        "提出前に会計システムへ予算残高を照会するため、外部システムの障害で失敗することがあります（その場合は再試行できます）。",
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
        openWorldHint: true,
      },
    },
    async ({ requestId, confirm, previewToken }) => {
      const denied = scopeGuard(granted, "submit_request");
      if (denied !== undefined) return toolFailure(denied);

      const stateFailure = classify(store, requestId, ["draft"]);
      if (stateFailure !== undefined) return toolFailure(stateFailure);

      const request = store.requests.get(requestId) as WorkflowRequest;

      // 外部システムに問い合わせる。落ちているときは「再試行できる失敗」として返す
      let remainingYen: number;
      try {
        remainingYen = (await budgetApi.check(request.category, request.amountYen)).remainingYen;
      } catch (error) {
        console.error(`[upstream] budget check failed for ${requestId}:`, error);
        return toolFailure({
          code: "upstream_unavailable",
          what: "予算残高を照会する会計システムに接続できませんでした。申請はまだ提出されていません。",
          next: "2 秒ほど待って同じ引数で呼び直してください。数分続く場合は、Web 画面から提出するようユーザーに案内してください。",
          retryable: true,
          retryAfterSeconds: 2,
        });
      }

      const preview = previewSubmit(store, requestId);
      if (!preview.ok) return toolFailure(internalFailure("submit_request", new Error(preview.message)));

      if (!confirm) {
        return {
          content: [
            {
              type: "text",
              text:
                `【ドライラン】${requestId} を提出すると次のようになります。\n` +
                `状態: ${preview.currentStatus} → ${preview.nextStatus}\n` +
                `通知先: ${preview.notifyTo.join(", ")}\n` +
                `区分 ${request.category} の残予算: ${remainingYen} 円（この申請 ${request.amountYen} 円を差し引いた後の額）\n` +
                `確定するには confirm: true と previewToken: ${preview.previewToken} を付けて再度呼び出してください。`,
            },
          ],
        };
      }

      if (previewToken === undefined) {
        return toolFailure({
          code: "invalid_argument",
          what: "confirm: true で呼ばれましたが previewToken がありません。",
          next: "confirm を省略して呼び出し、返ってきた previewToken をそのまま渡してください。ドライランを 1 回通す必要があります。",
          retryable: false,
        });
      }
      if (previewToken !== preview.previewToken) {
        return toolFailure({
          code: "invalid_state",
          what: `previewToken が現在の申請と一致しません（受け取った値: ${quoteArg(previewToken)}）。`,
          next: "確認後に申請の内容が変わっています。confirm を省略して呼び出し直し、内容を確認してから確定してください。",
          retryable: false,
        });
      }

      const applied = applySubmit(store, requestId);
      if (!applied.ok) return toolFailure(internalFailure("submit_request", new Error(applied.message)));

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

  // ── 5. 決着をつける（requests:approve・二段階・構造化エラー） ───────────
  server.registerTool(
    "decide_request",
    {
      title: "申請を承認・却下・差し戻しする（確認つき）",
      description:
        "審査中の申請に決裁を下します。決裁は取り消せないため二段階です。" +
        "まず confirm を付けずに呼んで、何段目の決裁か・確定後の状態・通知先・previewToken を受け取り、" +
        "ユーザーの承諾を得てから confirm: true と previewToken を付けて再度呼び出してください。" +
        "reject と return_for_changes では comment（理由）が必須です。" +
        "失敗したときは error.code と error.retryable で原因を判別できます。",
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
        applied: z.boolean().describe("実際に決裁したか（ドライランと失敗では false）"),
        requestId: z.string(),
        decision: z.string(),
        currentStatus: z.string().describe("現在の状態"),
        nextStatus: z.string().describe("確定後の状態（ドライランでは見込み）"),
        stepLabel: z.string().describe("何段目の決裁か（例: 1/2 段目）"),
        finalizes: z.boolean().describe("この決裁で審査が終わるか"),
        notifyTo: z.array(z.string()).describe("通知先"),
        previewToken: z.string().optional().describe("確定時に渡す値（ドライランのときだけ返す）"),
        error: z
          .object({
            code: z.string(),
            retryable: z.boolean(),
            retryAfterSeconds: z.number().int().optional(),
          })
          .optional()
          .describe("失敗したときだけ返る機械可読なエラー"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ requestId, decision, comment, confirm, previewToken }) => {
      /** 失敗しても outputSchema の形を保つための土台 */
      const base = {
        applied: false,
        requestId,
        decision,
        currentStatus: store.requests.get(requestId)?.status ?? "unknown",
        nextStatus: "unknown",
        stepLabel: "-",
        finalizes: false,
        notifyTo: [] as string[],
      };

      const denied = scopeGuard(granted, "decide_request");
      if (denied !== undefined) return toolFailureWith(denied, base);

      const stateFailure = classify(store, requestId, ["in_review"]);
      if (stateFailure !== undefined) return toolFailureWith(stateFailure, base);

      if (decision !== "approve" && (comment === undefined || comment.trim() === "")) {
        return toolFailureWith(
          {
            code: "invalid_argument",
            what: `decision="${decision}" では comment（理由）が必須です。`,
            next: "申請者に表示される理由を 1 文以上で comment に指定して呼び直してください。理由を書けない場合はユーザーに確認してください。",
            retryable: false,
          },
          base,
        );
      }

      const preview = previewDecision(store, requestId, decision, comment);
      if (!preview.ok) {
        return toolFailureWith(internalFailure("decide_request", new Error(preview.message)), base);
      }

      const detail = {
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
          structuredContent: { applied: false, ...detail, previewToken: preview.previewToken },
        };
      }

      if (previewToken === undefined || previewToken !== preview.previewToken) {
        const failure: ToolFailure =
          previewToken === undefined
            ? {
                code: "invalid_argument",
                what: "confirm: true で呼ばれましたが previewToken がありません。",
                next: "confirm を省略して呼び出し、返ってきた previewToken をそのまま渡してください。",
                retryable: false,
              }
            : {
                code: "invalid_state",
                what: `previewToken が現在の申請と一致しません（受け取った値: ${quoteArg(previewToken)}）。`,
                next: "確認後に申請の内容か決裁内容が変わっています。confirm を省略して呼び直し、内容を確認してから確定してください。",
                retryable: false,
              };
        return toolFailureWith(failure, { ...base, ...detail });
      }

      const applied = applyDecision(store, requestId, decision, comment);
      if (!applied.ok) {
        return toolFailureWith(internalFailure("decide_request", new Error(applied.message)), {
          ...base,
          ...detail,
        });
      }

      return {
        content: [
          {
            type: "text",
            text:
              `${requestId} を ${decision} しました（${applied.stepLabel} / 状態: ${applied.status}）\n` +
              (applied.finalizes
                ? "審査は終了しました。"
                : `次の承認者: ${preview.notifyTo.join(", ")}`),
          },
        ],
        structuredContent: { applied: true, ...detail, nextStatus: applied.status },
      };
    },
  );

  // ── 6. 補足を残す（requests:write） ────────────────────────────────────
  server.registerTool(
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
      const denied = scopeGuard(granted, "comment_on_request");
      if (denied !== undefined) return toolFailure(denied);

      const failure = classify(store, requestId, STATUSES);
      if (failure !== undefined) return toolFailure(failure);

      const result = addComment(store, requestId, body, links ?? []);
      if (!result.ok) {
        return toolFailure(internalFailure("comment_on_request", new Error(result.message)));
      }
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

  return { server, store };
}
