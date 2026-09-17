/**
 * 問題3 の解答：ログの出し分けとレベル絞り込み
 *
 * 実行： docker compose exec node npx tsx src/session08/practice/q3-logging.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import {
  LoggingMessageNotificationSchema,
  SetLevelRequestSchema,
  type ServerNotification,
} from "@modelcontextprotocol/sdk/types.js";

/** syslog 準拠の 8 段階。左が最も詳細で、右が最も重大 */
const LEVEL_ORDER = [
  "debug", "info", "notice", "warning", "error", "critical", "alert", "emergency",
] as const;
type LogLevel = (typeof LEVEL_ORDER)[number];

const TOTAL_STEPS = 5;
const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

// ① logging ケイパビリティを宣言する（宣言しないと送信時に SDK が例外を投げる）
const server = new McpServer(
  { name: "q3-logging", version: "1.0.0" },
  { capabilities: { logging: {} } },
);

let currentLevel: LogLevel = "info";

// ② logging/setLevel は SDK が自動処理しないので自分で登録する
server.server.setRequestHandler(SetLevelRequestSchema, async (request) => {
  currentLevel = request.params.level as LogLevel;
  console.error(`[log] レベルを ${currentLevel} に変更しました`);
  return {}; // 空の結果を返すのが仕様
});

// ③ レベルで絞ってから送る
const sendLog = async (
  send: (notification: ServerNotification) => Promise<void>,
  level: LogLevel,
  message: string,
): Promise<void> => {
  if (LEVEL_ORDER.indexOf(level) < LEVEL_ORDER.indexOf(currentLevel)) return;
  try {
    await send({
      method: "notifications/message",
      params: { level, logger: "q3", data: { message } },
    });
  } catch (error) {
    console.error("[log] notifications/message の送信に失敗しました:", error);
  }
};

server.registerTool(
  "run_task",
  {
    title: "5 ステップの処理",
    description: "5 ステップの処理を行い、節目でログを送ります。",
    inputSchema: {},
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  },
  async (_args, extra) => {
    await sendLog(extra.sendNotification, "info", "処理を開始しました");
    for (let step = 0; step < TOTAL_STEPS; step++) {
      await sendLog(
        extra.sendNotification,
        "debug",
        `ステップ ${step + 1}/${TOTAL_STEPS} を実行しました`,
      );
    }
    await sendLog(extra.sendNotification, "info", "処理が完了しました");
    return { content: [{ type: "text", text: "完了しました" }] };
  },
);

// ---------------- 検証 ----------------
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "q3-client", version: "1.0.0" });

const counts: Record<string, number> = {};
client.setNotificationHandler(LoggingMessageNotificationSchema, (notification) => {
  const level = notification.params.level;
  counts[level] = (counts[level] ?? 0) + 1;
});

await server.connect(serverTransport);
await client.connect(clientTransport);

const measure = async (index: number, label: string): Promise<void> => {
  for (const key of Object.keys(counts)) delete counts[key];
  await client.callTool({ name: "run_task", arguments: {} });
  await sleep(50); // 通知の配送を待つ
  console.log(`[${index}/3] ${label}: info=${counts["info"] ?? 0} debug=${counts["debug"] ?? 0}`);
};

await measure(1, "level=info（既定）");
await client.setLoggingLevel("debug");
await measure(2, "level=debug");
await client.setLoggingLevel("error");
await measure(3, "level=error");

await client.close();
await server.close();
console.log("OK: 問題3 の条件を満たしています");
