/**
 * 問題7 の解答 ―― 進捗通知を送るサーバーを HTTP で公開する
 *
 * 背面で起動（SSE モード）:
 *   docker compose exec -d node sh -c 'npx tsx src/review03/q7-serve.ts > /tmp/review03-q7.log 2>&1'
 * 背面で起動（JSON レスポンスモード）:
 *   docker compose exec -d -e MCP_HTTP_JSON=on node sh -c 'npx tsx src/review03/q7-serve.ts > /tmp/review03-q7.log 2>&1'
 * 停止:
 *   docker compose exec node sh -c 'kill $(cat /tmp/review03-q7.pid)'
 */
import { unlinkSync, writeFileSync } from "node:fs";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { log, startHttpEndpoint } from "./q4-http.js";
import { registerScanTool } from "./q5-scan-tool.js";

// 問題4 と別の PID ファイルを使う（同じ名前にすると停止対象を取り違える）
const PID_FILE = "/tmp/review03-q7.pid";
const jsonResponse = process.env["MCP_HTTP_JSON"] === "on";

const running = await startHttpEndpoint({
  serverFactory: () => {
    const server = new McpServer({ name: "review03-q7", version: "1.0.0" });
    registerScanTool(server);
    return server;
  },
  jsonResponse,
});

writeFileSync(PID_FILE, `${process.pid}\n`, "utf8");
log(
  `待ち受け開始: http://${running.host}:${running.port}${running.endpoint}` +
    `（応答形式=${jsonResponse ? "application/json" : "text/event-stream"}）`,
);
log(`PID ${process.pid}（${PID_FILE}）`);

let shuttingDown = false;

async function shutdown(signal: string): Promise<void> {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  log(`${signal} を受け取りました。セッションを閉じて終了します`);
  await running.close();
  try {
    unlinkSync(PID_FILE);
  } catch {
    // すでに消えていてもよい
  }
  process.exit(0);
}

process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));
