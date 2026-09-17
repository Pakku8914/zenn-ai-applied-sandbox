/**
 * 寿命管理つきの起動エントリーポイント
 *
 * 起動: docker compose exec -d -e MCP_MAX_SESSIONS=2 node sh -c 'npx tsx src/session07/serve-http-ttl.ts > /tmp/http.log 2>&1'
 */
import { unlinkSync, writeFileSync } from "node:fs";

import { resolveDocsRoot } from "../mid01/config.js";
import { createDocSearchServer } from "../mid01/create-server.js";
import { DEFAULT_HOST, DEFAULT_PORT, log, startHttpServer } from "./http-server.js";
import { resolveTrustPolicy } from "./origin.js";
import { startSessionReaper } from "./session-reaper.js";

const PID_FILE = "/tmp/mcp-http.pid";
const host = process.env["MCP_HTTP_HOST"] ?? DEFAULT_HOST;
const port = Number(process.env["MCP_HTTP_PORT"] ?? String(DEFAULT_PORT));
const docsRoot = resolveDocsRoot([]);

const running = await startHttpServer({
  serverFactory: () => createDocSearchServer({ docsRoot }),
  host,
  port,
  trust: resolveTrustPolicy(process.env, port),
  maxSessions: Number(process.env["MCP_MAX_SESSIONS"] ?? "32"),
});

const stopReaper = startSessionReaper(running, {
  idleMs: Number(process.env["MCP_SESSION_IDLE_MS"] ?? "3000"),
  maxAgeMs: Number(process.env["MCP_SESSION_MAX_AGE_MS"] ?? "60000"),
  intervalMs: Number(process.env["MCP_REAPER_INTERVAL_MS"] ?? "1000"),
});

writeFileSync(PID_FILE, `${process.pid}\n`, "utf8");
log(`寿命管理つきで待ち受け開始: http://${host}:${port}${running.endpoint}`);
log(`PID ${process.pid}。停止するには kill ${process.pid}`);

process.on("SIGTERM", () => {
  void (async () => {
    stopReaper();
    await running.close();
    try {
      unlinkSync(PID_FILE);
    } catch {
      // すでに消えていてもよい
    }
    process.exit(0);
  })();
});
