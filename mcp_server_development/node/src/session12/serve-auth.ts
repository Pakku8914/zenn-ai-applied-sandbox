/**
 * モック認可サーバーの起動口
 *
 * 背面で起動（テスト用の鋳造口も開ける）:
 *   docker compose exec -d -e MCP_AS_DEBUG=on node \
 *     sh -c 'npx tsx src/session12/serve-auth.ts > /tmp/as.log 2>&1'
 * 停止:
 *   docker compose exec node sh -c 'kill $(cat /tmp/mcp-as.pid)'
 */
import { unlinkSync, writeFileSync } from "node:fs";
import http from "node:http";

import { DEFAULT_AS_PORT, createAuthServer } from "./auth-server.js";

const PID_FILE = "/tmp/mcp-as.pid";
const host = process.env["MCP_AS_HOST"] ?? "127.0.0.1";
const port = Number(process.env["MCP_AS_PORT"] ?? String(DEFAULT_AS_PORT));
const issuer = process.env["MCP_AS_ISSUER"] ?? `http://${host}:${port}`;
const debug = process.env["MCP_AS_DEBUG"] === "on";

const { listener, jwk } = createAuthServer({
  issuer,
  debug,
  tokenTtlSeconds: Number(process.env["MCP_AS_TOKEN_TTL"] ?? "300"),
});
const server = http.createServer(listener);

await new Promise<void>((resolve, reject) => {
  const onError = (error: Error): void => reject(error);
  server.once("error", onError);
  server.listen(port, host, () => {
    server.removeListener("error", onError);
    resolve();
  });
});

writeFileSync(PID_FILE, `${process.pid}\n`, "utf8");
console.error(`[mock-as] issuer=${issuer} で待ち受けています（kid=${jwk.kid}）`);
console.error(`[mock-as] テスト用の鋳造口: ${debug ? "有効（MCP_AS_DEBUG=on）" : "無効"}`);
console.error(`[mock-as] PID ${process.pid}（${PID_FILE}）`);

async function shutdown(signal: string): Promise<void> {
  console.error(`[mock-as] ${signal} を受け取りました`);
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
  try {
    unlinkSync(PID_FILE);
  } catch {
    // すでに消えていてもよい
  }
  process.exit(0);
}

process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));
