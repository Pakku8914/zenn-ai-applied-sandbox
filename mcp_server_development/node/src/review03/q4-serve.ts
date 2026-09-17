/**
 * 問題4 の解答 ―― 起動用エントリーポイント
 *
 * 背面で起動:
 *   docker compose exec -d node sh -c 'npx tsx src/review03/q4-serve.ts > /tmp/review03-http.log 2>&1'
 * 停止:
 *   docker compose exec node sh -c 'kill $(cat /tmp/review03-http.pid)'
 *
 * 環境変数
 *   MCP_HTTP_HOST       待ち受けアドレス（既定 127.0.0.1）
 *   MCP_HTTP_PORT       待ち受けポート（既定 3939）
 *   MCP_MAX_SESSIONS    同時セッション数の上限（既定 4）
 *   MCP_HTTP_JSON=on    SSE ではなく application/json で応答する
 *   MCP_TRUST_CHECK=off Origin / Host 検証を外す（実験用・本番禁止）
 */
import { unlinkSync, writeFileSync } from "node:fs";

import { createDocSearchLiteServer } from "./create-server-lite.js";
import {
  DEFAULT_HOST,
  DEFAULT_PORT,
  log,
  resolveTrustPolicy,
  startHttpEndpoint,
} from "./q4-http.js";

const PID_FILE = "/tmp/review03-http.pid";

const host = process.env["MCP_HTTP_HOST"] ?? DEFAULT_HOST;
const port = Number(process.env["MCP_HTTP_PORT"] ?? String(DEFAULT_PORT));
const maxSessions = Number(process.env["MCP_MAX_SESSIONS"] ?? "4");
const jsonResponse = process.env["MCP_HTTP_JSON"] === "on";
const trust = resolveTrustPolicy(port);

const running = await startHttpEndpoint({
  // ★ ここが本章の軸。サーバー定義のファクトリをそのまま渡すだけ
  serverFactory: createDocSearchLiteServer,
  host,
  port,
  trust,
  maxSessions,
  jsonResponse,
});

writeFileSync(PID_FILE, `${process.pid}\n`, "utf8");
log(`待ち受け開始: http://${running.host}:${running.port}${running.endpoint}`);
log(
  `Origin 検証: ${trust.enabled ? "有効" : "無効（実験用）"}` +
    ` / 応答形式: ${jsonResponse ? "application/json" : "text/event-stream"}` +
    ` / 同時セッション上限: ${maxSessions}`,
);
log(`PID ${process.pid}（${PID_FILE}）。停止するには kill ${process.pid}`);

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

// stdio と違い、HTTP サーバーは自分で終了処理を書く必要がある
process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));
