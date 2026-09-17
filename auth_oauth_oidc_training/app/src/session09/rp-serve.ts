// RP を実際のポートで起動して、ブラウザから触るためのスクリプト。
// 使い方: docker compose exec app npx tsx src/session09/rp-serve.ts
// そのあとホスト OS のブラウザで http://localhost:3100/login を開きます。
import { serve } from "@hono/node-server";
import { createRpApp } from "./rp-server.js";

const app = await createRpApp();
// hostname を 0.0.0.0 にしないと、ホスト OS からポートマッピング経由で届かない
const server = serve({ fetch: app.fetch, port: 3100, hostname: "0.0.0.0" }, (info) => {
  console.log(`RP を起動しました（port ${info.port}）。http://localhost:3100/login を開いてください。`);
});
process.on("SIGINT", () => server.close(() => process.exit(0))); // 掴んだポートを必ず離す
