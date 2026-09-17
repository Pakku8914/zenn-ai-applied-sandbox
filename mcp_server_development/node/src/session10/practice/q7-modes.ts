/**
 * 問題7 の解答：モードに応じたツールの出し入れと削減効果の計測
 *
 * 実行： docker compose exec node npx tsx src/session10/practice/q7-modes.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ToolListChangedNotificationSchema } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import { measureTools } from "../tokens.js";
import { ROOMS, createRoomStore, searchReservations } from "./rooms.js";

type RegisteredTool = ReturnType<McpServer["registerTool"]>;

const RESERVATION_ID = /^rsv-\d{3}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

const store = createRoomStore();
const server = new McpServer({ name: "rooms-q7", version: "1.0.0" });

/** 6 本のツールを登録し、ハンドルを名前で引けるようにする */
const tools: Record<string, RegisteredTool> = {
  search_reservations: server.registerTool(
    "search_reservations",
    {
      title: "予約を探す",
      description: "会議室の予約を条件で絞り込み、要約を返します。ID が分かっているときは get_reservation を使ってください。",
      inputSchema: {
        roomId: z.enum(ROOMS).optional().describe("会議室"),
        date: z.string().regex(DATE).optional().describe("対象日（YYYY-MM-DD）"),
        limit: z.number().int().min(1).max(20).default(10).describe("返す件数（既定 10）"),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ roomId, date, limit }) => ({
      content: [
        { type: "text", text: `${searchReservations(store, { roomId, date, limit }).length} 件` },
      ],
    }),
  ),
  get_reservation: server.registerTool(
    "get_reservation",
    {
      title: "予約の詳細を見る",
      description: "予約 1 件の詳細を返します。ID が不明なときは search_reservations で探してください。",
      inputSchema: { reservationId: z.string().regex(RESERVATION_ID).describe("予約 ID") },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ reservationId }) => ({
      content: [
        { type: "text", text: store.reservations.get(reservationId)?.title ?? "見つかりません" },
      ],
    }),
  ),
  check_room_availability: server.registerTool(
    "check_room_availability",
    {
      title: "空き時間を確認する",
      description: "指定日に空いている時間帯を返します。予約を作る前に必ず確認してください。",
      inputSchema: {
        date: z.string().regex(DATE).describe("対象日（YYYY-MM-DD）"),
        roomId: z.enum(ROOMS).optional().describe("会議室"),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ date }) => ({ content: [{ type: "text", text: `${date} の空き枠: 9:00, 13:00` }] }),
  ),
  book_room: server.registerTool(
    "book_room",
    {
      title: "会議室を予約する",
      description: "会議室を予約します。空き時間は check_room_availability で確認してください。",
      inputSchema: {
        roomId: z.enum(ROOMS).describe("会議室"),
        date: z.string().regex(DATE).describe("対象日（YYYY-MM-DD）"),
        startHour: z.number().int().min(9).max(20).describe("開始時刻（時、9〜20）"),
        title: z.string().min(1).max(40).describe("会議名"),
      },
      annotations: { destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ roomId, date, startHour, title }) => ({
      content: [{ type: "text", text: `${roomId} ${date} ${startHour}:00「${title}」を予約しました` }],
    }),
  ),
  cancel_reservation: server.registerTool(
    "cancel_reservation",
    {
      title: "予約をキャンセルする",
      description: "予約をキャンセルします。会議名や時間の変更だけなら book_room を使ってください。",
      inputSchema: {
        reservationId: z.string().regex(RESERVATION_ID).describe("予約 ID"),
        reason: z.string().min(1).max(200).describe("キャンセル理由"),
      },
      annotations: { destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ reservationId }) => ({
      content: [{ type: "text", text: `${reservationId} をキャンセルしました` }],
    }),
  ),
  purge_reservation: server.registerTool(
    "purge_reservation",
    {
      title: "予約を物理削除する（管理者専用）",
      description: "予約を完全に削除します。監査記録も残りません。管理者のみが使用します。",
      inputSchema: { reservationId: z.string().regex(RESERVATION_ID).describe("予約 ID") },
      annotations: { destructiveHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ reservationId }) => ({
      content: [{ type: "text", text: `${reservationId} を削除しました` }],
    }),
  ),
};

const MODES: Record<string, string[]> = {
  admin: Object.keys(tools),
  guest: ["search_reservations", "get_reservation", "check_room_availability"],
  member: [
    "search_reservations",
    "get_reservation",
    "check_room_availability",
    "book_room",
    "cancel_reservation",
  ],
};

// ── 検証 ──
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "rooms-q7-client", version: "1.0.0" });

let listChangedCount = 0;
client.setNotificationHandler(ToolListChangedNotificationSchema, () => {
  listChangedCount++;
});

await server.connect(serverTransport);
await client.connect(clientTransport);

/** モードを適用する（全ツールに毎回 enable / disable を呼ぶ素直な実装） */
function applyMode(mode: string): void {
  const allowed = MODES[mode] ?? [];
  for (const [name, handle] of Object.entries(tools)) {
    if (allowed.includes(name)) handle.enable();
    else handle.disable();
  }
}

async function report(mode: string, baseChars?: number): Promise<number> {
  const measured = measureTools((await client.listTools()).tools);
  const diff =
    baseChars === undefined
      ? ""
      : `（-${(((baseChars - measured.totalChars) / baseChars) * 100).toFixed(1)}%）`;
  console.log(
    `[${mode.padEnd(6)}] ${measured.rows.length} 本 / ${String(measured.totalChars).padStart(4)} chars / ` +
      `約 ${measured.totalTokens} tokens${diff}`,
  );
  return measured.totalChars;
}

const base = await report("admin");
applyMode("guest");
await report("guest", base);
applyMode("member");
await report("member", base);

// 無効なツールを直接呼ぶとどうなるか
applyMode("guest");
try {
  await client.callTool({ name: "purge_reservation", arguments: { reservationId: "rsv-002" } });
  console.log("[直接呼び出し] 呼べてしまった（想定外）");
} catch (error) {
  console.log(`[直接呼び出し] guest モードで purge_reservation を呼ぶ → ${String(error).slice(0, 60)}`);
}

console.log(`list_changed 受信回数: ${listChangedCount}`);

await client.close();
await server.close();
console.log("OK: 問題7 の確認が完了しました");
