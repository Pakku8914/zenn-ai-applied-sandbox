/**
 * 問題7 の解答：list_changed の送りすぎを抑える
 *
 * 実行： docker compose exec node npx tsx src/session08/practice/q7-list-changed.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ToolListChangedNotificationSchema } from "@modelcontextprotocol/sdk/types.js";

const CHANGE_EVENTS = 100;
const DEBOUNCE_MS = 50;
const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const server = new McpServer({ name: "q7-list-changed", version: "1.0.0" });

// ---- 抑制なし ----
server.registerTool(
  "reload_stations_naive",
  {
    title: "観測所定義の再読み込み（抑制なし）",
    description: "100 件の観測所定義を更新し、1 件ごとに list_changed を送ります。",
    inputSchema: {},
    annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: false },
  },
  async () => {
    for (let i = 0; i < CHANGE_EVENTS; i++) {
      // ❌ 1 件ごとに通知。受け取ったクライアントは毎回 tools/list を呼び直す
      await server.server.sendToolListChanged();
    }
    return {
      content: [{ type: "text", text: `${CHANGE_EVENTS} 件を更新しました（通知 ${CHANGE_EVENTS} 回）` }],
    };
  },
);

// ---- デバウンスあり ----
// 「予約済みなら何もしない」方式を選びました。最後の更新から数える方式（毎回タイマーを
// 張り直す）だと、更新が途切れない限り通知が永久に遅れるためです。一覧の変更は
// 「早く 1 回知らせる」ほうが価値が高いので、先頭の 1 件から一定時間後に送ります。
let debounceTimer: NodeJS.Timeout | undefined;

const scheduleToolListChanged = (): void => {
  if (debounceTimer !== undefined) return; // すでに予約済み
  debounceTimer = setTimeout(() => {
    debounceTimer = undefined;
    void server.server.sendToolListChanged();
  }, DEBOUNCE_MS);
};

server.registerTool(
  "reload_stations_debounced",
  {
    title: "観測所定義の再読み込み（デバウンスあり）",
    description: "100 件の観測所定義を更新し、list_changed は 1 回だけ送ります。",
    inputSchema: {},
    annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: false },
  },
  async () => {
    for (let i = 0; i < CHANGE_EVENTS; i++) {
      scheduleToolListChanged(); // ✅ 何回呼んでも通知は 1 回
    }
    return {
      content: [{ type: "text", text: `${CHANGE_EVENTS} 件を更新しました（通知は 1 回）` }],
    };
  },
);

// ---------------- 検証 ----------------
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "q7-client", version: "1.0.0" });

let received = 0;
client.setNotificationHandler(ToolListChangedNotificationSchema, () => {
  received += 1;
});

await server.connect(serverTransport);
await client.connect(clientTransport);

await client.callTool({ name: "reload_stations_naive", arguments: {} });
await sleep(200); // 通知の配送を待つ
console.log(`[1/2] デバウンスなし: 変更イベント=${CHANGE_EVENTS} / クライアント受信=${received}`);

received = 0;
await client.callTool({ name: "reload_stations_debounced", arguments: {} });
await sleep(200); // デバウンスのタイマーが発火するのを待つ
console.log(`[2/2] デバウンスあり: 変更イベント=${CHANGE_EVENTS} / クライアント受信=${received}`);

if (debounceTimer !== undefined) clearTimeout(debounceTimer); // 後始末
await client.close();
await server.close();
console.log("OK: 問題7 の条件を満たしています");
