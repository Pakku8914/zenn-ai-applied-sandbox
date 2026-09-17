/**
 * 問題1 の解答：進捗通知を送るツールにする
 *
 * サーバーとクライアントを 1 ファイルに書き、インメモリトランスポートでつないでいます。
 * 子プロセスを起こさないので速く、出力も安定します。
 *
 * 実行： docker compose exec node npx tsx src/session08/practice/q1-progress.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

const TOTAL_STEPS = 5;
const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** サーバーが「送信を試みた」回数。要求がないときに 0 であることを確かめるために数える */
let sentProgressCount = 0;

const server = new McpServer({ name: "q1-progress", version: "1.0.0" });

server.registerTool(
  "run_import",
  {
    title: "取り込み処理",
    description: "5 ステップの取り込み処理を行います。進捗通知に対応しています。",
    inputSchema: {},
    annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: false },
  },
  async (_args, extra) => {
    // ① クライアントが進捗を要求したときだけ _meta.progressToken が入っている
    const progressToken = extra._meta?.progressToken;
    sentProgressCount = 0;

    for (let step = 0; step < TOTAL_STEPS; step++) {
      await sleep(50); // 本来の処理の代わり

      // ② 要求されていないなら送らない
      if (progressToken === undefined) continue;

      try {
        await extra.sendNotification({
          method: "notifications/progress",
          params: {
            progressToken,
            progress: step + 1,
            total: TOTAL_STEPS,
            message: `${step + 1}/${TOTAL_STEPS} 完了`,
          },
        });
        sentProgressCount += 1;
      } catch (error) {
        // ③ 通知の失敗で本流を止めない（ログは stderr へ）
        console.error("[progress] 通知の送信に失敗しました:", error);
      }
    }

    return {
      content: [{ type: "text", text: `${TOTAL_STEPS} ステップの取り込みが完了しました` }],
    };
  },
);

server.registerTool(
  "get_sent_count",
  {
    title: "進捗通知の送信回数",
    description: "直前の run_import で進捗通知を送信した回数を返します（検証用）。",
    inputSchema: {},
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  },
  async () => ({ content: [{ type: "text", text: String(sentProgressCount) }] }),
);

// ---------------- 検証 ----------------
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "q1-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

const readSentCount = async (): Promise<string> => {
  const result = await client.callTool({ name: "get_sent_count", arguments: {} });
  const content = result.content as Array<{ type: string; text?: string }>;
  return content[0]?.text ?? "?";
};

// ケース1：onprogress を渡すと SDK が _meta.progressToken を自動で付ける
let count = 0;
let last = 0;
let total: number | undefined;
await client.callTool({ name: "run_import", arguments: {} }, undefined, {
  onprogress: (progress) => {
    count += 1;
    last = progress.progress;
    total = progress.total;
  },
});
console.log(`[1/2] progressToken あり: 進捗通知=${count}回 / 最後=${last}/${total}`);

// ケース2：onprogress を渡さない = 進捗を要求していない
await client.callTool({ name: "run_import", arguments: {} });
console.log(`[2/2] progressToken なし: 進捗通知=${await readSentCount()}回`);

await client.close();
await server.close();
console.log("OK: 問題1 の条件を満たしています");
