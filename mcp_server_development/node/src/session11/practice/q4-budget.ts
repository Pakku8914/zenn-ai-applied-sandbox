/**
 * 問題4 の解答：一覧に上限付き返却を入れる
 *
 * 実行： docker compose exec node npx tsx src/session11/practice/q4-budget.ts
 *
 * 上限に達したことを 3 か所で伝えます。
 *   ① content の最後の行（モデルが文章として読む）
 *   ② structuredContent.omitted（機械が読む）
 *   ③ hasMore と nextCursor（続きの取り方）
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { toolFailureWith, type ToolFailure } from "../errors.js";
import { BUDGET, fitLines } from "../respond.js";
import {
  RESERVATION_STATUSES,
  ROOMS,
  createRoomStore,
  searchReservations,
  summaryLine,
  type RoomStore,
} from "./rooms.js";

/** カーソルは不透明な文字列にする。中身の意味はサーバーだけが知る */
function encodeCursor(afterId: string): string {
  return Buffer.from(JSON.stringify({ v: 1, afterId }), "utf8").toString("base64url");
}

function decodeCursor(cursor: string): string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
  } catch {
    throw new Error("cursor decode failed");
  }
  if (
    typeof parsed !== "object" ||
    parsed === null ||
    (parsed as { v?: unknown }).v !== 1 ||
    typeof (parsed as { afterId?: unknown }).afterId !== "string"
  ) {
    throw new Error("cursor shape invalid");
  }
  return (parsed as { afterId: string }).afterId;
}

/** 失敗しても outputSchema の形を保つための空の値 */
const EMPTY = { total: 0, returned: 0, hasMore: false, items: [] } as const;

export function createSearchServer(store: RoomStore = createRoomStore()): McpServer {
  const server = new McpServer({ name: "rooms-search", version: "1.0.0" });

  server.registerTool(
    "search_reservations",
    {
      title: "会議室予約を探す",
      description:
        "会議室の予約を条件で絞り込み、要約の一覧を返します（議題・参加者・変更履歴は返しません）。" +
        "ID が既に分かっているときは get_reservation を使ってください。" +
        `返す量には上限（${BUDGET.listChars} 文字）があり、超えた分は省略して件数を伝えます。` +
        "続きは nextCursor を cursor に渡して取得します。",
      inputSchema: {
        roomId: z.enum(ROOMS).optional().describe("会議室。この 3 室以外は存在しません"),
        date: z
          .string()
          .regex(/^\d{4}-\d{2}-\d{2}$/)
          .optional()
          .describe("開催日（YYYY-MM-DD）"),
        status: z
          .array(z.enum(RESERVATION_STATUSES))
          .max(3)
          .optional()
          .describe("状態で絞り込む（複数指定可）。省略するとすべての状態を対象にします"),
        query: z.string().min(1).max(100).optional().describe("会議名と議題へのキーワード検索"),
        limit: z.number().int().min(1).max(50).default(10).describe("返す件数（1〜50、既定は 10）"),
        cursor: z.string().optional().describe("前回の結果の nextCursor をそのまま渡します"),
      },
      outputSchema: {
        total: z.number().int().describe("条件に一致した総件数"),
        returned: z.number().int().describe("このレスポンスに含まれる件数"),
        hasMore: z.boolean().describe("続きがあるか（上限で切った場合も true）"),
        nextCursor: z.string().optional().describe("続きを取得するためのカーソル"),
        omitted: z.number().int().optional().describe("返却上限のために省略した件数"),
        items: z
          .array(
            z.object({
              id: z.string(),
              roomId: z.string(),
              title: z.string(),
              date: z.string(),
              startHour: z.number().int(),
              hours: z.number().int(),
              status: z.string(),
              organizerName: z.string(),
            }),
          )
          .describe("予約の要約。議題・参加者・変更履歴は含みません"),
        error: z
          .object({
            code: z.string(),
            retryable: z.boolean(),
            retryAfterSeconds: z.number().int().optional(),
          })
          .optional(),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ roomId, date, status, query, limit, cursor }) => {
      let afterId: string | undefined;
      if (cursor !== undefined) {
        try {
          afterId = decodeCursor(cursor);
        } catch (error) {
          // 例外の中身は分類にだけ使い、返す文面は自分で書く
          const failure: ToolFailure = {
            code: "invalid_argument",
            what: "cursor の値を解釈できませんでした。",
            next: "cursor を省略して最初のページから取得し直してください。cursor には前回の結果の nextCursor をそのまま渡します。",
            retryable: false,
          };
          console.error("[invalid cursor]", error);
          return toolFailureWith(failure, EMPTY);
        }
      }

      const result = searchReservations(store, { roomId, date, status, query, limit, afterId });

      const fitted = fitLines(
        result.items.map(summaryLine),
        BUDGET.listChars,
        "cursor に nextCursor を渡すと続きが取れます。roomId や date で絞り込むほうが確実です",
      );

      // 上限で切った場合も「続きがある」として扱う
      const truncated = fitted.omitted > 0;
      const lastIncluded = result.items[fitted.included - 1];
      const hasMore = result.hasMore || truncated;
      const nextCursor =
        hasMore && lastIncluded !== undefined ? encodeCursor(lastIncluded.id) : undefined;

      const header =
        `${result.total} 件中 ${fitted.included} 件を返しました` + (hasMore ? "（続きがあります）" : "");

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
    },
  );

  return server;
}

// ── 検証 ────────────────────────────────────────────────────────────────
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "practice-q4", version: "1.0.0" });
await createSearchServer().connect(serverTransport);
await client.connect(clientTransport);

type SearchOutput = {
  total: number;
  returned: number;
  hasMore: boolean;
  nextCursor?: string;
  omitted?: number;
  items: Array<{ id: string }>;
};

function text(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): string {
  return (result.content as Array<{ text?: string }> | undefined)?.[0]?.text ?? "";
}

const first = await client.callTool({ name: "search_reservations", arguments: { limit: 50 } });
const firstOut = first.structuredContent as SearchOutput;
console.log(
  `[1/4] limit=50: total=${firstOut.total} returned=${firstOut.returned} ` +
    `omitted=${firstOut.omitted} hasMore=${firstOut.hasMore} ` +
    `nextCursor=${firstOut.nextCursor === undefined ? "なし" : "あり"}`,
);
console.log(`[2/4] 議題を含まない=${!text(first).includes("前回の宿題の確認")}`);

const second = await client.callTool({
  name: "search_reservations",
  arguments: { limit: 50, cursor: firstOut.nextCursor },
});
const secondOut = second.structuredContent as SearchOutput;
console.log(
  `[3/4] 続き: returned=${secondOut.returned} 先頭=${secondOut.items[0]?.id ?? "-"}`,
);

const broken = await client.callTool({
  name: "search_reservations",
  arguments: { cursor: "not-a-cursor" },
});
const brokenCode = /^\[(\w+)\]/.exec(text(broken))?.[1] ?? "-";
console.log(`[4/4] 壊れた cursor: isError=${broken.isError === true} code=${brokenCode}`);

await client.close();
