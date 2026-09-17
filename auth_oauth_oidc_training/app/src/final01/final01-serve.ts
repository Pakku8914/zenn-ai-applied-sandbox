// web-app（3100）と api-service（4100）を同時に起動して、ブラウザから通しで確かめるスクリプト。
// 使い方: docker compose exec app npx tsx src/final01/final01-serve.ts
import { serve } from "@hono/node-server";
import { createAuditSink } from "./final01-audit.js";
import { BookstoreAccounts } from "./final01-authz.js";
import { createFinalApiApp } from "./final01-api-service.js";
import { createFinalWebApp } from "./final01-rp.js";

// 監査ログは 1 行 1 JSON で標準出力へ。本番ではログ基盤への送信に差し替えます
const audit = createAuditSink((line) => console.log(line));
const api = createFinalApiApp({ accounts: new BookstoreAccounts(), audit });
// hostname を 0.0.0.0 にしないと、ホスト OS からポートマッピング経由で届きません
const apiServer = serve({ fetch: api.fetch, port: 4100, hostname: "0.0.0.0" });
const web = await createFinalWebApp({ audit });
const webServer = serve({ fetch: web.app.fetch, port: 3100, hostname: "0.0.0.0" });
console.log("2 つのサーバーを起動しました。http://localhost:3100/login を開いてください");

// Ctrl+C で 2 つとも閉じる（掴んだポートを離さないと次の起動に失敗します）
process.on("SIGINT", () => {
  apiServer.close();
  webServer.close(() => process.exit(0));
});
