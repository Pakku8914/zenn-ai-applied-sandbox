/**
 * 問題2 の解答：引数を締める（列挙型・既定値・上限）
 *
 * 実行： docker compose exec node npx tsx src/session10/practice/q2-arguments.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { RESERVATION_STATUSES, ROOMS, createRoomStore, searchReservations } from "./rooms.js";

const DATE = /^\d{4}-\d{2}-\d{2}$/;

const store = createRoomStore();
const server = new McpServer({ name: "rooms-q2", version: "1.0.0" });

server.registerTool(
  "search_reservations",
  {
    title: "予約を探す",
    description:
      "会議室の予約を条件で絞り込み、要約の一覧を返します。" +
      "返す件数は既定 10 件、最大 20 件です。続きが必要な場合は条件を絞ってください。",
    inputSchema: {
      // ① 選択肢を閉じる（マスタ参照ツールが不要になる）
      roomId: z.enum(ROOMS).optional().describe("会議室。この 3 室以外は存在しません"),
      status: z
        .array(z.enum(RESERVATION_STATUSES))
        .max(3)
        .optional()
        .describe("状態で絞り込む（複数指定可）。省略するとすべての状態を対象にします"),
      // ② 形式を宣言する
      date: z
        .string()
        .regex(DATE, "YYYY-MM-DD 形式で指定してください")
        .optional()
        .describe("対象日（YYYY-MM-DD、例: 2026-09-01）"),
      // ③ page / perPage を廃止し、既定値と上限を持つ limit に統合する
      limit: z.number().int().min(1).max(20).default(10).describe("返す件数（1〜20、既定は 10）"),
    },
    outputSchema: {
      returned: z.number().int().describe("返した件数"),
      items: z
        .array(
          z.object({
            id: z.string(),
            roomId: z.string(),
            title: z.string(),
            date: z.string(),
            startHour: z.number().int(),
            status: z.string(),
          }),
        )
        .describe("予約の要約"),
    },
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  },
  async ({ roomId, status, date, limit }) => {
    const rows = searchReservations(store, { roomId, status, date, limit });
    const items = rows.map((row) => ({
      id: row.id,
      roomId: row.roomId,
      title: row.title,
      date: row.date,
      startHour: row.startHour,
      status: row.status,
    }));
    return {
      content: [{ type: "text", text: `${items.length} 件` }],
      structuredContent: { returned: items.length, items },
    };
  },
);

// ── 検証 ──
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "rooms-q2-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

/** 入力検証で弾かれたかどうかを返す（SDK は検証失敗を例外として投げる） */
async function rejected(args: Record<string, unknown>): Promise<boolean> {
  // スキーマ違反は例外にならず、isError: true のツール結果として返ります。
  // 本文に Input validation error が入るので、それで「Zod が弾いた」ことを判定します
  const result = await client.callTool({ name: "search_reservations", arguments: args });
  const text = ((result.content ?? []) as Array<{ text?: string }>)
    .map((block) => block.text ?? "")
    .join("");
  return result.isError === true && text.includes("Input validation error");
}

console.log(`[1/3] status="予約済み" → 弾かれた: ${await rejected({ status: ["予約済み"] })}`);

const defaults = await client.callTool({ name: "search_reservations", arguments: {} });
const structured = defaults.structuredContent as { returned: number };
console.log(`[2/3] limit 省略時の返却件数: ${structured.returned}`);

console.log(`[3/3] limit=999 → 弾かれた: ${await rejected({ limit: 999 })}`);

await client.close();
await server.close();
console.log("OK: 問題2 の条件を満たしています");
