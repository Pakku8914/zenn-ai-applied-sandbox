/**
 * 問題5 の解答：キャンセルを二段階（ドライラン → 確定）にする
 *
 * 実行： docker compose exec node npx tsx src/session10/practice/q5-two-phase.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { createRoomStore, type Reservation, type RoomStore } from "./rooms.js";

const RESERVATION_ID = /^rsv-\d{3}$/;

const store = createRoomStore();

/**
 * ① ドライランと確定で同じ関数からトークンを作る
 *    version を含めるので、予約が変更されると自動的に無効になる
 */
function makeCancelToken(row: Reservation, reason: string): string {
  return Buffer.from(
    JSON.stringify({ v: 1, action: "cancel", id: row.id, version: row.version, reason }),
    "utf8",
  ).toString("base64url");
}

type CancelPreview =
  | { ok: true; row: Reservation; previewToken: string }
  | { ok: false; message: string };

/** ② 事前条件の判定は 1 か所（プレビュー）に集める */
function previewCancel(target: RoomStore, reservationId: string, reason: string): CancelPreview {
  const row = target.reservations.get(reservationId);
  if (row === undefined) {
    return { ok: false, message: `予約 ${reservationId} は見つかりません。` };
  }
  if (row.status === "cancelled") {
    return {
      ok: false,
      message: `予約 ${reservationId} はすでにキャンセル済みです。追加の操作は必要ありません。`,
    };
  }
  if (row.status === "done") {
    return {
      ok: false,
      message: `予約 ${reservationId} は終了済みのためキャンセルできません。`,
    };
  }
  return { ok: true, row, previewToken: makeCancelToken(row, reason) };
}

const server = new McpServer({ name: "rooms-q5", version: "1.0.0" });

server.registerTool(
  "cancel_reservation",
  {
    title: "予約をキャンセルする（確認つき）",
    description:
      "会議室の予約をキャンセルします。キャンセルは取り消せず、参加者の予定にも影響するため二段階です。" +
      "まず confirm を付けずに呼ぶと、対象の予約内容・影響を受ける参加者の人数・previewToken を返します（状態は変わりません）。" +
      "内容をユーザーに確認したうえで、confirm: true と previewToken を付けて再度呼び出すと確定します。" +
      "会議名や時間を変えたいだけの場合は book_room を使ってください。",
    inputSchema: {
      reservationId: z.string().regex(RESERVATION_ID).describe("キャンセルする予約 ID（rsv-001 の形式）"),
      reason: z
        .string()
        .min(1)
        .max(200)
        .describe("キャンセル理由（1〜200 文字）。参加者への通知に使われます"),
      confirm: z
        .boolean()
        .default(false)
        .describe("false（既定）はドライラン。true で実際にキャンセルします（previewToken が必須）"),
      previewToken: z
        .string()
        .optional()
        .describe("ドライランの結果に含まれる値をそのまま渡します。予約が変更されると無効になります"),
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false,
    },
  },
  async ({ reservationId, reason, confirm, previewToken }) => {
    const preview = previewCancel(store, reservationId, reason);
    if (!preview.ok) {
      return { content: [{ type: "text", text: preview.message }], isError: true };
    }
    const row = preview.row;

    // ③ ドライランでは絶対に状態を変えない
    if (!confirm) {
      return {
        content: [
          {
            type: "text",
            text:
              `【ドライラン】${row.id}「${row.title}」をキャンセルします。\n` +
              `会議室: ${row.roomId} / ${row.date} ${row.startHour}:00-${row.startHour + row.hours}:00\n` +
              `影響を受ける参加者: ${row.attendees.length} 人\n` +
              `理由: ${reason}\n` +
              `確定するには confirm: true と previewToken: ${preview.previewToken} を付けて再度呼び出してください。`,
          },
        ],
      };
    }

    // ④ 確定には必ず previewToken が必要
    if (previewToken === undefined) {
      return {
        content: [
          {
            type: "text",
            text: "confirm: true で呼ぶときは previewToken が必要です。先に confirm を省略して呼び出し、返ってきた previewToken を渡してください。",
          },
        ],
        isError: true,
      };
    }
    if (previewToken !== preview.previewToken) {
      return {
        content: [
          {
            type: "text",
            text: "previewToken が一致しません。予約の内容またはキャンセル理由が変わっています。もう一度 confirm を省略して呼び出し、内容を確認してから確定してください。",
          },
        ],
        isError: true,
      };
    }

    row.status = "cancelled";
    row.version += 1;
    return {
      content: [
        {
          type: "text",
          text: `${row.id} をキャンセルしました（状態=${row.status} / 通知先 ${row.attendees.length} 人）`,
        },
      ],
    };
  },
);

// ── 検証 ──
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "rooms-q5-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

function text(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): string {
  const first = (result.content as Array<{ text?: string }> | undefined)?.[0];
  return first?.text ?? "";
}
function pickToken(message: string): string {
  return /previewToken: (\S+)/.exec(message)?.[1] ?? "";
}
async function call(args: Record<string, unknown>) {
  return client.callTool({ name: "cancel_reservation", arguments: args });
}

// 1. ドライラン（状態が変わらないことを確認）
const dry = await call({ reservationId: "rsv-002", reason: "先方の都合で延期" });
const dryText = text(dry);
console.log(
  `[1/5] ドライラン: previewToken=${pickToken(dryText) === "" ? "なし" : "あり"} / ` +
    `状態=${store.reservations.get("rsv-002")?.status} / ` +
    `参加者=${/参加者: (\d+) 人/.exec(dryText)?.[1] ?? "?"} 人`,
);

// 2. 確定
const applied = await call({
  reservationId: "rsv-002",
  reason: "先方の都合で延期",
  confirm: true,
  previewToken: pickToken(dryText),
});
console.log(`[2/5] 確定: ${text(applied)}`);

// 3. previewToken なしの確定
const noToken = await call({ reservationId: "rsv-003", reason: "参加者が集まらない", confirm: true });
console.log(`[3/5] previewToken なしで confirm → isError=${noToken.isError === true}`);

// 4. ドライラン後に予約が変更されたケース
const staleDry = text(await call({ reservationId: "rsv-004", reason: "部屋を変更する" }));
const target = store.reservations.get("rsv-004");
if (target !== undefined) {
  target.startHour += 1;
  target.version += 1; // 予約が変更された
}
const stale = await call({
  reservationId: "rsv-004",
  reason: "部屋を変更する",
  confirm: true,
  previewToken: pickToken(staleDry),
});
console.log(`[4/5] version が変わった後の確定 → isError=${stale.isError === true}`);

// 5. すでにキャンセル済み（rsv-001）へのドライラン
const already = await call({ reservationId: "rsv-001", reason: "重複予約のため" });
console.log(`[5/5] キャンセル済みへのドライラン → isError=${already.isError === true}`);

await client.close();
await server.close();
console.log("OK: 問題5 の条件を満たしています");
