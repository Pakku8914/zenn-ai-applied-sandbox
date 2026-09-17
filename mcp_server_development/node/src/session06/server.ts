/**
 * チーム稼働ダッシュボード（セッション6 版）― stdio エントリーポイント
 *
 * 実行： docker compose exec node npx tsx src/session06/server.ts
 * （単体で起動すると stderr に 1 行出したあと沈黙します。それが正常です）
 *
 * stdout は JSON-RPC の通信路そのものなので console.log は絶対に使いません。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createDashboardServer } from "./create-server.js";

const server = createDashboardServer();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard] stdio でリクエストを待機しています");
