/**
 * 社内申請ワークフロー MCP サーバー（Bad 実装：18 本のエンドポイントをそのまま写す）
 *
 * OpenAPI 定義から機械生成したような形にしています。
 * registerTool を 18 回手で並べても結果は同じです（定義の合計サイズを測るのが目的です）。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import {
  addComment,
  applyDecision,
  applySubmit,
  createStore,
  getRequestDetail,
  saveRequest,
  searchRequests,
  type Category,
  type Status,
  type Store,
} from "./data.js";

/** 入力スキーマの形（zod のスキーマを値に持つオブジェクト） */
type RawShape = Record<string, z.ZodType>;

type MirroredTool = {
  name: string;
  title: string;
  description: string;
  inputSchema: RawShape;
};

const requestId = z.string().describe("申請 ID");

/** エンドポイント 1 本 = ツール 1 本。説明文は API ドキュメントの文章をそのまま流用している */
const ENDPOINT_TOOLS: MirroredTool[] = [
  {
    name: "list_requests",
    title: "申請一覧",
    description:
      "GET /api/requests を呼び出します。申請の一覧を取得します。クエリパラメータ status, applicantId, page, perPage を指定できます。",
    inputSchema: {
      status: z.string().optional().describe("状態"),
      applicantId: z.string().optional().describe("申請者 ID"),
      page: z.number().optional().describe("ページ番号"),
      perPage: z.number().optional().describe("1 ページあたりの件数"),
    },
  },
  {
    name: "search_requests",
    title: "申請検索",
    description:
      "GET /api/requests/search を呼び出します。題名と本文を全文検索します。クエリパラメータ q, page, perPage を指定できます。",
    inputSchema: {
      q: z.string().describe("検索キーワード"),
      page: z.number().optional().describe("ページ番号"),
      perPage: z.number().optional().describe("1 ページあたりの件数"),
    },
  },
  {
    name: "get_request_detail",
    title: "申請詳細",
    description: "GET /api/requests/{id} を呼び出します。申請 1 件の詳細を取得します。",
    inputSchema: { id: requestId },
  },
  {
    name: "create_request",
    title: "申請作成",
    description:
      "POST /api/requests を呼び出します。申請を新規作成します。リクエストボディに title, category, amountYen, body を指定します。",
    inputSchema: {
      title: z.string().describe("題名"),
      category: z.string().describe("申請区分"),
      amountYen: z.number().describe("金額"),
      body: z.string().describe("本文"),
    },
  },
  {
    name: "update_request",
    title: "申請更新",
    description:
      "PATCH /api/requests/{id} を呼び出します。申請を部分更新します。リクエストボディに title, category, amountYen, body を指定します。",
    inputSchema: {
      id: requestId,
      title: z.string().optional().describe("題名"),
      category: z.string().optional().describe("申請区分"),
      amountYen: z.number().optional().describe("金額"),
      body: z.string().optional().describe("本文"),
    },
  },
  {
    name: "delete_request",
    title: "申請削除",
    description: "DELETE /api/requests/{id} を呼び出します。申請を削除します。",
    inputSchema: { id: requestId },
  },
  {
    name: "submit_request",
    title: "申請提出",
    description: "POST /api/requests/{id}/submit を呼び出します。申請を提出します。",
    inputSchema: { id: requestId },
  },
  {
    name: "approve_request",
    title: "申請承認",
    description:
      "POST /api/requests/{id}/approve を呼び出します。申請を承認します。リクエストボディに comment を指定できます。",
    inputSchema: { id: requestId, comment: z.string().optional().describe("コメント") },
  },
  {
    name: "reject_request",
    title: "申請却下",
    description:
      "POST /api/requests/{id}/reject を呼び出します。申請を却下します。リクエストボディに comment を指定します。",
    inputSchema: { id: requestId, comment: z.string().optional().describe("コメント") },
  },
  {
    name: "return_request",
    title: "申請差し戻し",
    description:
      "POST /api/requests/{id}/return を呼び出します。申請を申請者に差し戻します。リクエストボディに comment を指定します。",
    inputSchema: { id: requestId, comment: z.string().optional().describe("コメント") },
  },
  {
    name: "withdraw_request",
    title: "申請取り下げ",
    description:
      "POST /api/requests/{id}/withdraw を呼び出します。申請者本人が申請を取り下げます。",
    inputSchema: { id: requestId },
  },
  {
    name: "list_comments",
    title: "コメント一覧",
    description: "GET /api/requests/{id}/comments を呼び出します。コメントの一覧を取得します。",
    inputSchema: { id: requestId },
  },
  {
    name: "create_comment",
    title: "コメント投稿",
    description:
      "POST /api/requests/{id}/comments を呼び出します。コメントを投稿します。リクエストボディに body を指定します。",
    inputSchema: { id: requestId, body: z.string().describe("コメント本文") },
  },
  {
    name: "list_attachments",
    title: "添付一覧",
    description: "GET /api/requests/{id}/attachments を呼び出します。添付の一覧を取得します。",
    inputSchema: { id: requestId },
  },
  {
    name: "upload_attachment",
    title: "添付アップロード",
    description:
      "POST /api/requests/{id}/attachments を呼び出します。添付ファイルをアップロードします。リクエストボディに fileName と contentBase64 を指定します。",
    inputSchema: {
      id: requestId,
      fileName: z.string().describe("ファイル名"),
      contentBase64: z.string().describe("ファイル内容（base64）"),
    },
  },
  {
    name: "list_history",
    title: "履歴一覧",
    description: "GET /api/requests/{id}/history を呼び出します。変更履歴を取得します。",
    inputSchema: { id: requestId },
  },
  {
    name: "list_approvals",
    title: "承認ルート",
    description:
      "GET /api/requests/{id}/approvals を呼び出します。承認ルートと承認状況を取得します。",
    inputSchema: { id: requestId },
  },
  {
    name: "list_categories",
    title: "申請区分一覧",
    description: "GET /api/categories を呼び出します。申請区分マスタを取得します。",
    inputSchema: {},
  },
];

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** 18 本のツールの実処理。API のレスポンスをそのまま JSON で返す造りです */
function callMirroredApi(store: Store, name: string, args: Record<string, unknown>): string {
  const id = str(args.id);
  const request = store.requests.get(id);

  switch (name) {
    case "list_requests":
      return JSON.stringify(
        searchRequests(store, {
          ...(args.status === undefined ? {} : { status: [str(args.status) as Status] }),
          ...(args.applicantId === undefined ? {} : { applicantId: str(args.applicantId) }),
          limit: typeof args.perPage === "number" ? args.perPage : 20,
        }),
      );
    case "search_requests":
      return JSON.stringify(searchRequests(store, { query: str(args.q), limit: 20 }));
    case "get_request_detail":
      return JSON.stringify(getRequestDetail(store, id, [])?.request ?? { error: "not found" });
    case "create_request":
      return JSON.stringify(
        saveRequest(store, {
          title: str(args.title),
          category: str(args.category) as Category,
          amountYen: typeof args.amountYen === "number" ? args.amountYen : 0,
          body: str(args.body),
        }),
      );
    case "update_request":
      return JSON.stringify(saveRequest(store, { requestId: id, ...args }));
    case "delete_request":
      return JSON.stringify({ deleted: store.requests.delete(id) });
    case "submit_request":
      return JSON.stringify(applySubmit(store, id));
    case "approve_request":
      return JSON.stringify(applyDecision(store, id, "approve", str(args.comment)));
    case "reject_request":
      return JSON.stringify(applyDecision(store, id, "reject", str(args.comment)));
    case "return_request":
      return JSON.stringify(applyDecision(store, id, "return_for_changes", str(args.comment)));
    case "withdraw_request":
      return JSON.stringify({ error: "取り下げは Web 画面からのみ実行できます" });
    case "list_comments":
      return JSON.stringify(request?.comments ?? []);
    case "create_comment":
      return JSON.stringify(addComment(store, id, str(args.body), []));
    case "list_attachments":
      return JSON.stringify(request?.attachments ?? []);
    case "upload_attachment":
      return JSON.stringify({ error: "アップロードはこの環境では未対応です" });
    case "list_history":
      return JSON.stringify(request?.history ?? []);
    case "list_approvals":
      return JSON.stringify(request?.approvals ?? []);
    case "list_categories":
      return JSON.stringify(["expense", "purchase", "leave", "travel"]);
    default:
      return JSON.stringify({ error: `unknown tool: ${name}` });
  }
}

export function createMirroredServer(store: Store = createStore()): McpServer {
  const server = new McpServer({ name: "workflow-requests-mirrored", version: "1.0.0" });

  for (const tool of ENDPOINT_TOOLS) {
    server.registerTool(
      tool.name,
      { title: tool.title, description: tool.description, inputSchema: tool.inputSchema },
      async (args) => ({
        content: [
          { type: "text", text: callMirroredApi(store, tool.name, args as Record<string, unknown>) },
        ],
      }),
    );
  }

  return server;
}
