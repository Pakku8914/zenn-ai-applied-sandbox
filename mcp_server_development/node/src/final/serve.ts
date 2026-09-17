/**
 * サンドボックス用の起動口（PID ファイルつき）
 *
 * 認可サーバー → MCP サーバーの順に起動します。
 *   docker compose exec -d -e MCP_AS_DEBUG=on node \
 *     sh -c 'npx tsx src/session12/serve-auth.ts > /tmp/as.log 2>&1'
 *   docker compose exec -d node \
 *     sh -c 'npx tsx src/final/serve.ts > /tmp/final.log 2>&1'
 * 停止:
 *   docker compose exec node sh -c 'kill $(cat /tmp/mcp-final.pid)'
 *
 * このファイルは配布物に入りません（cli.ts / index.ts から import されないため）。
 */
import { unlinkSync, writeFileSync } from "node:fs";

import { startProtectedServer } from "./serve-core.js";

const PID_FILE = "/tmp/mcp-final.pid";

function log(message: string): void {
  // サーバープロセスなので stdout には書かない
  console.error(`[final] ${message}`);
}

const running = await startProtectedServer({
  host: process.env["MCP_HTTP_HOST"] ?? "127.0.0.1",
  port: Number(process.env["MCP_HTTP_PORT"] ?? "3939"),
  issuer: process.env["MCP_AS_ISSUER"] ?? "http://127.0.0.1:9100",
  ...(process.env["MCP_AS_JWKS_URI"] === undefined
    ? {}
    : { jwksUri: process.env["MCP_AS_JWKS_URI"] }),
  ...(process.env["MCP_RESOURCE"] === undefined ? {} : { resource: process.env["MCP_RESOURCE"] }),
  tenantId: process.env["MCP_TENANT_ID"] ?? "acme",
  auditPepper: process.env["AUDIT_PEPPER"] ?? "sandbox-pepper",
  skipAudience: process.env["MCP_AUTH_SKIP_AUD"] === "on",
});

writeFileSync(PID_FILE, `${process.pid}\n`, "utf8");
log(`待ち受け開始: http://${running.host}:${running.port}${running.endpoint}`);
log(`resource（＝要求する aud）: ${running.resource}`);
log(`信頼する認可サーバー: ${running.issuer} / JWKS: ${running.jwksUri}`);
log(`aud 検証: ${running.skipAudience ? "❌ 無効（実験用。本番では絶対に無効化しない）" : "有効"}`);
log(`PID ${process.pid}（${PID_FILE}）`);

let shuttingDown = false;
async function shutdown(signal: string): Promise<void> {
  if (shuttingDown) return;
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
