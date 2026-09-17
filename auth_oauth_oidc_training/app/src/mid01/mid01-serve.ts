// 中間プロジェクト mid01: web-app（3100）と api-service（4100）を同時に起動して、
// ブラウザから通しで確かめるためのスクリプト。
// 使い方: docker compose exec app npx tsx src/mid01/mid01-serve.ts
// そのあとホスト OS のブラウザで http://localhost:3100/login を開きます。
import { serve } from "@hono/node-server";
import { createApiApp } from "./mid01-api-server.js";
import { createWebApp } from "./mid01-web-server.js";

// リソースサーバーを先に起動します（web-app が呼ぶ相手なので）
const apiApp = createApiApp({ log: (message) => console.log(message) });
// hostname を 0.0.0.0 にしないと、ホスト OS からポートマッピング経由で届きません
const apiServer = serve({ fetch: apiApp.fetch, port: 4100, hostname: "0.0.0.0" }, (info) => {
  console.log(`api-service を起動しました（port ${info.port}）`);
});

const webApp = await createWebApp();
const webServer = serve({ fetch: webApp.fetch, port: 3100, hostname: "0.0.0.0" }, (info) => {
  console.log(`web-app を起動しました（port ${info.port}）。http://localhost:3100/login を開いてください`);
});

// Ctrl+C で 2 つとも必ず閉じます（掴んだポートを離さないと次の起動に失敗します）
process.on("SIGINT", () => {
  apiServer.close();
  webServer.close(() => process.exit(0));
});
