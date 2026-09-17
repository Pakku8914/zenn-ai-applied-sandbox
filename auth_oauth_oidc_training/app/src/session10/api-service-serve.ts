// api-service を実際のポート（4100）で起動して、ホスト OS から触るためのスクリプト。
// 使い方: docker compose exec app npx tsx src/session10/api-service-serve.ts
import { serve } from "@hono/node-server";
import { createApiApp } from "./api-service-app.js";

const app = createApiApp();
// hostname を 0.0.0.0 にしないと、ホスト OS からポートマッピング経由で届かない
const server = serve({ fetch: app.fetch, port: 4100, hostname: "0.0.0.0" }, (info) => {
  console.log(`api-service を起動しました（port ${info.port}）。`);
  console.log("トークンなしで curl -i http://localhost:4100/api/whoami を試してください。");
});
process.on("SIGINT", () => server.close(() => process.exit(0))); // 掴んだポートを必ず離す
