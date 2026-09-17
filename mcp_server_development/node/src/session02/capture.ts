/**
 * 生電文キャプチャの実行スクリプト（クライアント側）
 *
 * src/session02/proxy.ts を「サーバー」として起動し、
 *   initialize → notifications/initialized → tools/list → tools/call
 * を実行します。プロキシが記録したログを最後に読み上げます。
 *
 * 実行： docker compose exec node npx tsx src/session02/capture.ts
 *        docker compose exec node npx tsx src/session02/capture.ts --pretty
 *
 * ここはクライアント側のスクリプトなので console.log を使ってかまいません。
 * 標準出力が通信路になるのはサーバー側のプロセスだけです。
 */
import { readFileSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const LOG_PATH = "captures/stdio.log";
const pretty = process.argv.includes("--pretty");

// command / args に本物のサーバーではなく中継スクリプトを指定するのが要点
const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/session02/proxy.ts"],
});
const client = new Client({ name: "capture-client", version: "1.0.0" });

// connect() の 1 行に initialize リクエストと notifications/initialized 通知が入っている
await client.connect(transport);
await client.listTools();
await client.callTool({ name: "add", arguments: { a: 2, b: 3 } });
await client.close();

// プロキシが最後の 1 行を書き終えるのを待つ（同期書き込みなので十分な余裕）
await sleep(200);

const lines = readFileSync(LOG_PATH, "utf8")
  .split("\n")
  .filter((line) => line.length > 0);

console.log(`=== キャプチャした電文（${LOG_PATH}） ===`);
lines.forEach((line, index) => {
  const direction = line.slice(0, 4);
  const payload = line.slice(5);
  if (pretty) {
    const label =
      direction === "C->S" ? "クライアント → サーバー" : "サーバー → クライアント";
    console.log(`\n--- [${index + 1}] ${label} ---`);
    console.log(JSON.stringify(JSON.parse(payload), null, 2));
  } else {
    console.log(`[${index + 1}] ${direction} ${payload}`);
  }
});
console.log(`\n合計 ${lines.length} 行`);
