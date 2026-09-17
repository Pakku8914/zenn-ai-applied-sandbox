/**
 * 問題1 の解答：似たツールの境界を説明文で引く
 *
 * 実行： docker compose exec node npx tsx src/session10/practice/q1-boundary.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { measureTools } from "../tokens.js";
import {
  RESERVATION_STATUSES,
  ROOMS,
  createRoomStore,
  formatReservationLine,
  searchReservations,
} from "./rooms.js";

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const RESERVATION_ID = /^rsv-\d{3}$/;

const store = createRoomStore();
const server = new McpServer({ name: "rooms-q1", version: "1.0.0" });

// ① 探すツール：要約だけを返し、詳細ツールへの誘導を説明文に入れる
server.registerTool(
  "search_reservations",
  {
    title: "予約を探す",
    description:
      "会議室の予約を条件で絞り込み、1 件 1 行の要約を返します（参加者や設備は返しません）。" +
      "予約 ID が既に分かっているときは get_reservation を使ってください。" +
      "返す件数は既定 10 件、最大 20 件です。",
    inputSchema: {
      roomId: z.enum(ROOMS).optional().describe("会議室。この 3 室以外は存在しません"),
      date: z.string().regex(DATE).optional().describe("対象日（YYYY-MM-DD）"),
      status: z
        .array(z.enum(RESERVATION_STATUSES))
        .max(3)
        .optional()
        .describe("状態で絞り込む（複数指定可）。省略するとすべての状態を対象にします"),
      query: z.string().min(1).max(40).optional().describe("会議名に対するキーワード検索（部分一致）"),
      limit: z.number().int().min(1).max(20).default(10).describe("返す件数（1〜20、既定は 10）"),
    },
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  },
  async ({ roomId, date, status, query, limit }) => {
    const rows = searchReservations(store, { roomId, date, status, query, limit });
    return {
      content: [
        { type: "text", text: [`${rows.length} 件`, ...rows.map(formatReservationLine)].join("\n") },
      ],
    };
  },
);

// ② 詳細ツール：ID を必須にし、探すツールへの誘導を説明文に入れる
server.registerTool(
  "get_reservation",
  {
    title: "予約の詳細を見る",
    description:
      "予約 1 件の詳細（会議名・会議室・日時・主催者・状態）を返します。" +
      "予約 ID が必要です。ID が分からないときは先に search_reservations で探してください。" +
      '参加者の一覧は既定では返しません。必要なときだけ include に "attendees" を指定してください。',
    inputSchema: {
      reservationId: z.string().regex(RESERVATION_ID).describe("予約 ID（rsv-001 の形式）"),
      include: z
        .array(z.enum(["attendees"]))
        .max(1)
        .optional()
        .describe("追加で含めるセクション。省略すると予約の基本情報だけを返します"),
    },
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  },
  async ({ reservationId, include }) => {
    const row = store.reservations.get(reservationId);
    if (row === undefined) {
      return {
        content: [
          {
            type: "text",
            text: `予約 ${reservationId} は見つかりません。search_reservations で ID を確認してください。`,
          },
        ],
        isError: true,
      };
    }
    const lines = [
      `${row.id} ${row.title}`,
      `会議室: ${row.roomId} / ${row.date} ${row.startHour}:00-${row.startHour + row.hours}:00`,
      `主催者: ${row.organizerId} / 状態: ${row.status}`,
    ];
    if (include?.includes("attendees") === true) {
      lines.push(`参加者（${row.attendees.length} 名）: ${row.attendees.join(", ")}`);
    }
    return { content: [{ type: "text", text: lines.join("\n") }] };
  },
);

// ── 検証 ──
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "rooms-q1-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

const tools = (await client.listTools()).tools;
const names = tools.map((tool) => tool.name).sort();
console.log(`[1/3] tools/list: ${names.length} 本 = ${names.join(", ")}`);

const search = tools.find((tool) => tool.name === "search_reservations");
const get = tools.find((tool) => tool.name === "get_reservation");
const searchToGet = search?.description?.includes("get_reservation") === true;
const getToSearch = get?.description?.includes("search_reservations") === true;
console.log(
  `[2/3] 境界の相互参照: search→get=${searchToGet ? "あり" : "なし"} / ` +
    `get→search=${getToSearch ? "あり" : "なし"}`,
);

const measured = measureTools(tools);
console.log(
  `[3/3] 定義サイズ: ${measured.rows.length} 本 / ${measured.totalChars} chars / 約 ${measured.totalTokens} tokens`,
);

await client.close();
await server.close();
console.log(
  searchToGet && getToSearch
    ? "OK: 問題1 の条件を満たしています"
    : "NG: 両方の description に相手のツール名を書いてください",
);
