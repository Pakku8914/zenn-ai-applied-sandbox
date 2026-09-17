/**
 * 問題5 の解答：一括取り消しの部分成功を返す
 *
 * 実行： docker compose exec node npx tsx src/session11/practice/q5-partial.ts
 *
 * 判断のポイント：1 件でも成功していれば isError を立てない。
 * 立てるとホストのリトライで二重取り消しが起きます。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { McpError } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import { toolFailure, type ToolFailure } from "../errors.js";
import { BUDGET, summarizeBatch, type ItemOutcome } from "../respond.js";
import { cancelReservation, createRoomStore, type ReservationStatus, type RoomStore } from "./rooms.js";

/** データ層の reason を ToolFailure に翻訳する。分類は 1 か所に集める */
function toFailure(reservationId: string, reason: "not_found" | "not_cancellable", status?: ReservationStatus): ToolFailure {
  if (reason === "not_found") {
    return {
      code: "not_found",
      what: "この ID の予約は存在しません。",
      next: `ID の形式は rsv-001 です。search_reservations で探して、返ってきた id を使ってください（受け取った値: ${reservationId}）。`,
      retryable: false,
    };
  }
  return {
    code: "invalid_state",
    what: `状態が ${status ?? "不明"} のため取り消せません。`,
    next: "取り消せるのは status が reserved の予約だけです。この ID は一括処理の対象から外してください。",
    retryable: false,
  };
}

export function createCancelServer(store: RoomStore = createRoomStore()): McpServer {
  const server = new McpServer({ name: "rooms-cancel", version: "1.0.0" });

  server.registerTool(
    "cancel_reservations",
    {
      title: "会議室予約をまとめて取り消す（確認つき）",
      description:
        `予約を最大 ${BUDGET.batchItems} 件までまとめて取り消します。` +
        "confirm を付けずに呼ぶと、各 ID が取り消せるかどうかだけを返します（何も変更しません）。" +
        "1 件ずつ処理し、途中で失敗しても残りは続行します（部分成功します）。" +
        "結果には成功した ID と失敗した ID の両方が含まれます。失敗した ID だけを直して呼び直してください。",
      inputSchema: {
        reservationIds: z
          .array(z.string().regex(/^rsv-\d{3}$/))
          .min(1)
          .max(BUDGET.batchItems)
          .describe(`取り消す予約 ID（1〜${BUDGET.batchItems} 件）`),
        reason: z
          .string()
          .min(10)
          .max(200)
          .describe("取り消しの理由（10〜200 文字）。主催者と参加者に通知されます"),
        confirm: z
          .boolean()
          .default(false)
          .describe("false（既定）はドライラン。true で実際に取り消します"),
      },
      outputSchema: {
        confirmed: z.boolean().describe("実際に取り消したか（ドライランでは false）"),
        succeeded: z.number().int(),
        failed: z.number().int(),
        items: z.array(
          z.object({
            id: z.string(),
            ok: z.boolean(),
            code: z.string().optional(),
            retryable: z.boolean().optional(),
          }),
        ),
        retryableIds: z.array(z.string()),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ reservationIds, reason, confirm }) => {
      // 重複は業務的にありえない引数。1 件も処理せずに返す
      const unique = new Set(reservationIds);
      if (unique.size !== reservationIds.length) {
        return toolFailure({
          code: "invalid_argument",
          what: "reservationIds に同じ ID が複数含まれています。",
          next: "重複を除いて呼び直してください。まだ 1 件も取り消していません。",
          retryable: false,
        });
      }

      const outcomes: ItemOutcome[] = [];
      for (const reservationId of reservationIds) {
        const reservation = store.reservations.get(reservationId);
        if (reservation === undefined) {
          outcomes.push({ id: reservationId, ok: false, failure: toFailure(reservationId, "not_found") });
          continue;
        }
        if (reservation.status !== "reserved") {
          outcomes.push({
            id: reservationId,
            ok: false,
            failure: toFailure(reservationId, "not_cancellable", reservation.status),
          });
          continue;
        }
        if (!confirm) {
          outcomes.push({
            id: reservationId,
            ok: true,
            detail: `取り消せます（${reservation.date} ${reservation.startHour}:00 / ${reservation.hours} 時間）`,
          });
          continue;
        }
        const result = cancelReservation(store, reservationId);
        if (!result.ok) {
          // ここに来たら分類漏れ。1 件だけ個別に処理させる
          outcomes.push({
            id: reservationId,
            ok: false,
            failure: toFailure(reservationId, result.reason, "status" in result ? result.status : undefined),
          });
          continue;
        }
        outcomes.push({
          id: reservationId,
          ok: true,
          detail: `${result.releasedHours} 時間を解放しました（理由: ${reason.slice(0, 20)}…）`,
        });
      }

      const summary = summarizeBatch(
        confirm ? "一括取り消し" : "一括取り消し（ドライラン）",
        outcomes,
      );

      // 全件失敗のときだけ isError を立てる
      const allFailed = summary.succeeded === 0;
      return {
        content: [{ type: "text", text: summary.text }],
        structuredContent: {
          confirmed: confirm,
          succeeded: summary.succeeded,
          failed: summary.failed,
          items: summary.items,
          retryableIds: summary.retryableIds,
        },
        ...(allFailed ? { isError: true } : {}),
      };
    },
  );

  return server;
}

// ── 検証 ────────────────────────────────────────────────────────────────
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "practice-q5", version: "1.0.0" });
await createCancelServer().connect(serverTransport);
await client.connect(clientTransport);

function text(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): string {
  return (result.content as Array<{ text?: string }> | undefined)?.[0]?.text ?? "";
}

const partial = await client.callTool({
  name: "cancel_reservations",
  arguments: {
    // rsv-002 / rsv-003 / rsv-004 は reserved、rsv-001 は done、rsv-999 は存在しない
    reservationIds: ["rsv-002", "rsv-003", "rsv-004", "rsv-001", "rsv-999"],
    reason: "全社会議と重複したため取り消します",
    confirm: true,
  },
});
console.log(`[1/3] 一部成功: isError=${partial.isError === true}`);
console.log(text(partial));

const allFailed = await client.callTool({
  name: "cancel_reservations",
  arguments: {
    reservationIds: ["rsv-001", "rsv-999"],
    reason: "重複していたため取り消します",
    confirm: true,
  },
});
const allFailedOut = allFailed.structuredContent as { succeeded: number; failed: number };
console.log(
  `\n[2/3] 全件失敗: isError=${allFailed.isError === true} ` +
    `succeeded=${allFailedOut.succeeded} failed=${allFailedOut.failed}`,
);

let layer = "ハンドラに届いた";
try {
  await client.callTool({
    name: "cancel_reservations",
    arguments: { reservationIds: ["rsv-002"], reason: "短い", confirm: true },
  });
} catch (error) {
  layer = error instanceof McpError ? `層2（code=${error.code}）` : `例外（${String(error)}）`;
}
console.log(`[3/3] reason が短い: ${layer}`);

await client.close();
