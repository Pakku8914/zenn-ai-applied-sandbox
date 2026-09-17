/**
 * 問題6 の解答：引数の改名を後方互換で行う
 *
 * 実行： docker compose exec node npx tsx src/session10/practice/q6-evolution.ts
 *
 * v1: room のみ（旧クライアントの基準）
 * v2: roomId（新）＋ room（廃止予定）の併存
 * v3: room を削除した版（黙って絞り込みが消えることの確認）
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { ROOMS, createRoomStore, searchReservations, type RoomId } from "./rooms.js";

type Variant = "v1" | "v2" | "v3";

function buildServer(variant: Variant): McpServer {
  const store = createRoomStore();
  const server = new McpServer({ name: `rooms-${variant}`, version: "1.0.0" });

  const roomIdField = z.enum(ROOMS).optional().describe("会議室（room-a / room-b / room-c）");

  const inputSchema: z.ZodRawShape =
    variant === "v1"
      ? { room: roomIdField }
      : variant === "v2"
        ? {
            roomId: roomIdField,
            room: z
              .enum(ROOMS)
              .optional()
              .describe("【廃止予定】roomId に置き換えてください。当面は同じ意味で動作します"),
          }
        : { roomId: roomIdField };

  server.registerTool(
    "search_reservations",
    {
      title: "予約を探す",
      description: "会議室の予約を条件で絞り込み、件数を返します。",
      inputSchema,
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async (args: Record<string, unknown>) => {
      const params = args as { roomId?: RoomId; room?: RoomId };

      // ① 両方指定はエラー（どちらを優先するかを推測させない）
      if (variant === "v2" && params.room !== undefined && params.roomId !== undefined) {
        return {
          content: [
            {
              type: "text",
              text: "room と roomId は同時に指定できません。roomId だけを使ってください。",
            },
          ],
          isError: true,
        };
      }

      // ② 旧引数の使用を記録する（stdout は通信路なので stderr へ）
      if (variant === "v2" && params.room !== undefined) {
        console.error("[deprecated] search_reservations: room は roomId に置き換えてください");
      }

      const roomId = variant === "v1" ? params.room : (params.roomId ?? params.room);
      const rows = searchReservations(store, {
        ...(roomId === undefined ? {} : { roomId }),
        limit: 100,
      });
      return { content: [{ type: "text", text: `${rows.length} 件` }] };
    },
  );
  return server;
}

async function callWith(variant: Variant, args: Record<string, unknown>): Promise<string> {
  const server = buildServer(variant);
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "q6-client", version: "1.0.0" });
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  const result = await client.callTool({ name: "search_reservations", arguments: args });
  const first = (result.content as Array<{ text?: string }>)[0];
  await client.close();
  await server.close();
  return result.isError === true ? "isError" : (first?.text ?? "");
}

console.log(`[v1] room="room-a"            → ${await callWith("v1", { room: "room-a" })}`);
console.log(`[v2] room="room-a"（廃止予定） → ${await callWith("v2", { room: "room-a" })}`);
console.log(`[v2] roomId="room-a"          → ${await callWith("v2", { roomId: "room-a" })}`);
console.log(
  `[v2] 両方指定                 → ${await callWith("v2", { room: "room-a", roomId: "room-a" })}`,
);
console.log(
  `[v3] room="room-a"（削除済み） → ${await callWith("v3", { room: "room-a" })}（絞り込みが黙って消えた）`,
);
console.log("OK: 問題6 の確認が完了しました");
