/**
 * 再開可能性の実験用サーバー（通知を出すサーバー ＋ EventStore）
 *
 * 起動: docker compose exec -d node sh -c 'npx tsx src/session07/serve-ticker.ts > /tmp/http.log 2>&1'
 * 停止: docker compose exec node sh -c 'kill $(cat /tmp/mcp-http.pid)'
 */
import { unlinkSync, writeFileSync } from "node:fs";

import { InMemoryEventStore } from "./event-store.js";
import { DEFAULT_HOST, DEFAULT_PORT, log, startHttpServer } from "./http-server.js";
import { resolveTrustPolicy } from "./origin.js";
import { createTickerServer } from "./ticker-server.js";

const PID_FILE = "/tmp/mcp-http.pid";
const host = process.env["MCP_HTTP_HOST"] ?? DEFAULT_HOST;
const port = Number(process.env["MCP_HTTP_PORT"] ?? String(DEFAULT_PORT));
const intervalMs = Number(process.env["TICKER_INTERVAL_MS"] ?? "1000");

const eventStore = new InMemoryEventStore(200);

const running = await startHttpServer({
  serverFactory: () => createTickerServer(intervalMs),
  host,
  port,
  trust: resolveTrustPolicy(process.env, port),
  eventStore,
});

writeFileSync(PID_FILE, `${process.pid}\n`, "utf8");
log(`ticker を http://${host}:${port}${running.endpoint} で公開しました（${intervalMs}ms ごとに通知）`);
log(`PID ${process.pid}。停止するには kill ${process.pid}`);

process.on("SIGTERM", () => {
  void (async () => {
    log(`保存済みイベント数: ${eventStore.size()}`);
    await running.close();
    try {
      unlinkSync(PID_FILE);
    } catch {
      // すでに消えていてもよい
    }
    process.exit(0);
  })();
});
