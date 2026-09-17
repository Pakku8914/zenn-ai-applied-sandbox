/**
 * ステートレス版の起動エントリーポイント
 *
 * 起動: docker compose exec -d node sh -c 'npx tsx src/session07/serve-stateless.ts > /tmp/http.log 2>&1'
 * 停止: docker compose exec node sh -c 'kill $(cat /tmp/mcp-http.pid)'
 */
import { unlinkSync, writeFileSync } from "node:fs";

import { resolveDocsRoot } from "../mid01/config.js";
import { createDocSearchServer } from "../mid01/create-server.js";
import { DEFAULT_HOST, DEFAULT_PORT, log } from "./http-server.js";
import { resolveTrustPolicy } from "./origin.js";
import { startStatelessServer } from "./stateless-http-server.js";

const PID_FILE = "/tmp/mcp-http.pid";
const host = process.env["MCP_HTTP_HOST"] ?? DEFAULT_HOST;
const port = Number(process.env["MCP_HTTP_PORT"] ?? String(DEFAULT_PORT));
const docsRoot = resolveDocsRoot([]);

const running = await startStatelessServer({
  serverFactory: () => createDocSearchServer({ docsRoot }),
  host,
  port,
  trust: resolveTrustPolicy(process.env, port),
});

writeFileSync(PID_FILE, `${process.pid}\n`, "utf8");
log(`ステートレス運用で待ち受け開始: http://${host}:${port}/mcp（docsRoot=${docsRoot}）`);
log(`PID ${process.pid}。停止するには kill ${process.pid}`);

process.on("SIGTERM", () => {
  void (async () => {
    log("SIGTERM を受け取りました。終了します");
    await running.close();
    try {
      unlinkSync(PID_FILE);
    } catch {
      // すでに消えていてもよい
    }
    process.exit(0);
  })();
});
