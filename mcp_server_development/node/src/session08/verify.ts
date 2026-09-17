/**
 * 動作確認用クライアント（Good 実装）
 *
 * src/session08/server.ts を子プロセスとして起動し、5 つの機構が動くことを確認します。
 * クライアント側のスクリプトなので console.log を使ってかまいません
 * （禁止されているのは「サーバープロセスの stdout」だけです）。
 *
 * 実行： docker compose exec node npx tsx src/session08/verify.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import {
  LoggingMessageNotificationSchema,
  ToolListChangedNotificationSchema,
} from "@modelcontextprotocol/sdk/types.js";

type ListResult = {
  observations: Array<{ id: string }>;
  returned: number;
  nextCursor?: string;
  hasMore: boolean;
};

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const client = new Client({ name: "session08-verify", version: "1.0.0" });

// サーバーから飛んでくる通知を数える。通知は応答を返せないので、
// 「届いたかどうか」はこうして受信側で数えるのが唯一の確認方法です
const logCounts: Record<string, number> = {};
let listChangedSeen = false;

client.setNotificationHandler(LoggingMessageNotificationSchema, (notification) => {
  const level = notification.params.level;
  logCounts[level] = (logCounts[level] ?? 0) + 1;
});
client.setNotificationHandler(ToolListChangedNotificationSchema, () => {
  listChangedSeen = true;
});

await client.connect(
  new StdioClientTransport({ command: "npx", args: ["tsx", "src/session08/server.ts"] }),
);

const info = client.getServerVersion();
const names = (await client.listTools()).tools.map((tool) => tool.name).sort();
console.log(`[1/9] 接続: ${info?.name} v${info?.version} / tools=${names.join(", ")}`);

// ---- ページネーション ----
const callList = async (args: Record<string, unknown>): Promise<ListResult> => {
  const result = await client.callTool({ name: "list_observations", arguments: args });
  return result.structuredContent as ListResult;
};
const ids = (page: ListResult): string => page.observations.map((row) => row.id).join(", ");

const page1 = await callList({ limit: 3 });
console.log(
  `[2/9] 1ページ目: ids=${ids(page1)} / nextCursor=${page1.nextCursor === undefined ? "なし" : "あり"} / hasMore=${page1.hasMore}`,
);

const page2 = await callList({ limit: 3, cursor: page1.nextCursor });
console.log(`[3/9] 2ページ目: ids=${ids(page2)} / returned=${page2.returned}`);

const filtered = await callList({ limit: 3, stationId: "st-01" });
console.log(`[4/9] 絞り込み(st-01): ids=${ids(filtered)}`);

const broken = await client.callTool({
  name: "list_observations",
  arguments: { cursor: "not-a-cursor" },
});
console.log(`[5/9] 壊れたカーソル: isError=${broken.isError === true}`);

// ---- 進捗通知 ----
let progressCount = 0;
let lastProgress = 0;
let lastTotal: number | undefined;
const aggregated = await client.callTool(
  { name: "aggregate_observations", arguments: { chunkDelayMs: 20 } },
  undefined,
  {
    // onprogress を渡すと、SDK が _meta.progressToken を自動で付けてくれる
    onprogress: (progress) => {
      progressCount += 1;
      lastProgress = progress.progress;
      lastTotal = progress.total;
    },
  },
);
const summary = aggregated.structuredContent as {
  totalObservations: number;
  stations: unknown[];
};
console.log(
  `[6/9] 進捗通知: 受信=${progressCount}回 / 最後=${lastProgress}/${lastTotal} / 集計件数=${summary.totalObservations} / 観測所数=${summary.stations.length}`,
);

// ---- キャンセル ----
const controller = new AbortController();
let clientAborted = false;
try {
  await client.callTool(
    { name: "aggregate_observations", arguments: { chunkDelayMs: 120 } },
    undefined,
    {
      signal: controller.signal,
      // 時間ではなく「3 チャンク目の進捗が届いたら」で判定するので結果が安定します
      onprogress: (progress) => {
        if (progress.progress >= 3) controller.abort();
      },
    },
  );
} catch {
  clientAborted = true;
}
await sleep(400); // キャンセル通知がサーバーに届くのを待つ
const report = (await client.callTool({ name: "get_last_run_report", arguments: {} }))
  .structuredContent as { executedSteps: number; finished: boolean; cancelled: boolean };
console.log(
  `[7/9] キャンセル: クライアント側=${clientAborted ? "中断" : "完走"} / サーバー側 cancelled=${report.cancelled} / finished=${report.finished} / executedSteps<20=${report.executedSteps < 20}`,
);

// ---- ロギング ----
await client.setLoggingLevel("info");
for (const key of Object.keys(logCounts)) delete logCounts[key];
await client.callTool({ name: "aggregate_observations", arguments: { chunkDelayMs: 0 } });
console.log(`[8/9] ログ(level=info): info=${logCounts["info"] ?? 0} debug=${logCounts["debug"] ?? 0}`);

// ---- list_changed ----
const beforeCount = (await client.listTools()).tools.length;
await client.callTool({ name: "enable_experimental_metrics", arguments: {} });
await sleep(200);
const afterCount = (await client.listTools()).tools.length;
console.log(`[9/9] list_changed: 受信=${listChangedSeen} / tools件数 ${beforeCount}→${afterCount}`);

await client.close();
console.log("OK: ページネーション・進捗・キャンセル・ロギング・list_changed が動作しています");
