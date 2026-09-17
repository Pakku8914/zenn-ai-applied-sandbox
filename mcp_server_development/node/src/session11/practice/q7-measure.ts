/**
 * 問題7 の解答：冗長な詳細を整形し、削減率を計測する
 *
 * 実行： docker compose exec node npx tsx src/session11/practice/q7-measure.ts
 *
 * 尺度はセッション10・11 と同じ（responseSize = 文字数と概算トークン）。
 * 冗長版と整形版でツール名・引数は同じにし、差が「返し方」だけになるようにします。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { toolFailure } from "../errors.js";
import { responseSize } from "../respond.js";
import { createRoomStore, type Reservation, type RoomStore } from "./rooms.js";

const AGENDA_CHARS = 400;
const SECTION_ITEMS = 5;
const ATTENDEE_NAMES = 5;

const INPUT = {
  reservationId: z.string().regex(/^rsv-\d{3}$/).describe("予約 ID（rsv-001 の形式）"),
  include: z
    .array(z.enum(["changeLog"]))
    .max(1)
    .optional()
    .describe("追加で含めるセクション。省略すると変更履歴を返しません"),
};

// ── 冗長版 ──────────────────────────────────────────────────────────────
export function createVerboseRoomServer(store: RoomStore = createRoomStore()): McpServer {
  const server = new McpServer({ name: "rooms-verbose", version: "1.0.0" });
  server.registerTool(
    "get_reservation",
    { title: "予約詳細", description: "予約 1 件の詳細を返します。", inputSchema: INPUT },
    async ({ reservationId }) => {
      const reservation = store.reservations.get(reservationId);
      // include を無視して全部返す。見つからない場合も isError を立てない
      if (reservation === undefined) {
        return { content: [{ type: "text", text: JSON.stringify({ error: "not found", reservationId }) }] };
      }
      return { content: [{ type: "text", text: JSON.stringify(reservation) }] };
    },
  );
  return server;
}

// ── 整形版 ──────────────────────────────────────────────────────────────
/**
 * 議題を上限まで切り、全文の在処を書き添える。
 *
 * 注意：room://{roomId}/{id} は「宣言」です。読める経路（resources/read）は
 * セッション6 のリソーステンプレートで用意する必要があります。
 * 読めないリンクを返すのは、再配達の窓口が無い不在票と同じです。
 */
function fitAgenda(reservation: Reservation): string {
  if (reservation.agenda.length <= AGENDA_CHARS) return reservation.agenda;
  return (
    `${reservation.agenda.slice(0, AGENDA_CHARS)}…\n` +
    `（議題は ${reservation.agenda.length} 文字あるため先頭 ${AGENDA_CHARS} 文字だけを返しました。` +
    `全文が必要なときはリソース room://${reservation.roomId}/${reservation.id} を読んでください）`
  );
}

function attendeeLine(reservation: Reservation): string {
  const shown = reservation.attendees.slice(0, ATTENDEE_NAMES);
  const rest = reservation.attendees.length - shown.length;
  const suffix = rest > 0 ? `ほか ${rest} 名（合計 ${reservation.attendees.length} 名）` : "";
  return `参加者: ${shown.join(", ")}${suffix}`;
}

export function createLeanRoomServer(store: RoomStore = createRoomStore()): McpServer {
  const server = new McpServer({ name: "rooms-lean", version: "1.0.0" });
  server.registerTool(
    "get_reservation",
    {
      title: "予約の詳細を見る",
      description:
        "予約 1 件の詳細（会議名・日時・会議室・状態・主催者・議題の要点・参加人数）を返します。" +
        `議題は ${AGENDA_CHARS} 文字を上限に切り、全文の参照を添えます。` +
        `参加者は先頭 ${ATTENDEE_NAMES} 名まで、変更履歴は include に指定したときだけ直近 ${SECTION_ITEMS} 件を返します。`,
      inputSchema: INPUT,
      outputSchema: {
        id: z.string(),
        roomId: z.string(),
        date: z.string(),
        status: z.string(),
        attendeeCount: z.number().int().describe("参加者の人数（名前は content 側に一部だけ）"),
        agendaChars: z.number().int().describe("議題の全文の文字数"),
        version: z.number().int().describe("変更回数。楽観的排他制御に使える"),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ reservationId, include }) => {
      const reservation = store.reservations.get(reservationId);
      if (reservation === undefined) {
        return toolFailure({
          code: "not_found",
          what: `予約 ${reservationId} は見つかりません。`,
          next: "ID の形式は rsv-001（3 桁ゼロ埋め）です。search_reservations で日付や会議名から探してください。",
          retryable: false,
        });
      }

      const lines = [
        `${reservation.id} ${reservation.title}`,
        `${reservation.roomId} / ${reservation.date} ${reservation.startHour}:00 から ${reservation.hours} 時間 / ${reservation.status}`,
        `主催: ${reservation.organizerName}（${reservation.organizerId}）`,
        attendeeLine(reservation),
        "議題:",
        fitAgenda(reservation),
      ];
      if (include?.includes("changeLog") === true) {
        const shown = reservation.changeLog.slice(-SECTION_ITEMS);
        const suffix =
          reservation.changeLog.length > shown.length ? `のうち直近 ${shown.length} 件` : "";
        lines.push(`変更履歴（全 ${reservation.changeLog.length} 件${suffix}）:`);
        lines.push(...shown.map((entry) => `- ${entry.at} ${entry.actorId} ${entry.action}`));
      }

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
      > = [{ type: "text", text: lines.join("\n") }];

      if (reservation.agenda.length > AGENDA_CHARS) {
        blocks.push({
          type: "resource_link",
          uri: `room://${reservation.roomId}/${reservation.id}`,
          name: `${reservation.id}-agenda`,
          title: `${reservation.title} の議題`,
          mimeType: "text/plain",
          description: `議題の全文（${reservation.agenda.length} 文字）`,
        });
      }

      return {
        content: blocks,
        // content と同じ文章を入れない。機械が使う要点だけを返す
        structuredContent: {
          id: reservation.id,
          roomId: reservation.roomId,
          date: reservation.date,
          status: reservation.status,
          attendeeCount: reservation.attendees.length,
          agendaChars: reservation.agenda.length,
          version: reservation.version,
        },
      };
    },
  );
  return server;
}

// ── 計測 ────────────────────────────────────────────────────────────────
async function connect(server: McpServer, label: string): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: `practice-q7-${label}`, version: "1.0.0" });
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  return client;
}

function rate(before: number, after: number): string {
  const value = ((before - after) / before) * 100;
  return `${value >= 0 ? "-" : "+"}${Math.abs(value).toFixed(1)}%`;
}

const verbose = await connect(createVerboseRoomServer(), "verbose");
const lean = await connect(createLeanRoomServer(), "lean");

const targets = [
  { label: "rsv-003（冗長）", args: { reservationId: "rsv-003", include: ["changeLog"] } },
  { label: "rsv-010（普通）", args: { reservationId: "rsv-010", include: ["changeLog"] } },
  { label: "存在しない ID", args: { reservationId: "rsv-999" } },
] as const;

console.log("=== 返却量の比較 ===");
console.log(`  ${"対象".padEnd(18)}${"verbose".padStart(9)}${"lean".padStart(9)}${"削減".padStart(9)}`);
const measured: Array<{ label: string; verboseChars: number; leanChars: number; leanTokens: number; verboseTokens: number }> = [];
for (const target of targets) {
  const v = await verbose.callTool({ name: "get_reservation", arguments: target.args });
  const l = await lean.callTool({ name: "get_reservation", arguments: target.args });
  const vs = responseSize(v);
  const ls = responseSize(l);
  measured.push({
    label: target.label,
    verboseChars: vs.chars,
    leanChars: ls.chars,
    verboseTokens: vs.tokens,
    leanTokens: ls.tokens,
  });
  console.log(
    `  ${target.label.padEnd(18)}${String(vs.chars).padStart(9)}${String(ls.chars).padStart(9)}` +
      `${rate(vs.chars, ls.chars).padStart(9)}`,
  );
}

const bulky = measured[0];
console.log("\n=== 概算トークン（rsv-003）===");
if (bulky !== undefined) {
  console.log(
    `  verbose=${bulky.verboseTokens} lean=${bulky.leanTokens} 削減=${rate(bulky.verboseTokens, bulky.leanTokens)}`,
  );
}

console.log("\n=== lean の内訳（rsv-003）===");
const leanBulky = await lean.callTool({
  name: "get_reservation",
  arguments: { reservationId: "rsv-003", include: ["changeLog"] },
});
const leanSize = responseSize(leanBulky);
const hasLink =
  (leanBulky.content as Array<{ type?: string }> | undefined)?.some(
    (block) => block.type === "resource_link",
  ) === true;
console.log(
  `  content=${leanSize.contentChars} structured=${leanSize.structuredChars} resource_link=${hasLink ? "あり" : "なし"}`,
);

console.log("\n=== 失敗の返し方 ===");
const verboseMissing = await verbose.callTool({
  name: "get_reservation",
  arguments: { reservationId: "rsv-999" },
});
const leanMissing = await lean.callTool({
  name: "get_reservation",
  arguments: { reservationId: "rsv-999" },
});
console.log(
  `  verbose: isError=${verboseMissing.isError === true} / lean: isError=${leanMissing.isError === true}`,
);
console.log("  ※ 失敗では lean のほうが長い。回復情報（次の一手）を書いているため。これは意図した増加です");

console.log("\n=== 判定 ===");
if (bulky !== undefined) {
  const reduction = ((bulky.verboseChars - bulky.leanChars) / bulky.verboseChars) * 100;
  console.log(`  rsv-003 の削減率が 60% 以上=${reduction >= 60}（実測 ${reduction.toFixed(1)}%）`);
}

await verbose.close();
await lean.close();
