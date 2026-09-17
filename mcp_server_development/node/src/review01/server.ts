/**
 * 日次ダッシュボードサーバー ― stdio トランスポートのエントリーポイント
 *
 * このファイルの仕事は「サーバー定義を stdio につなぐ」ことだけです。
 * stdout は JSON-RPC の通信路そのものなので、ログは必ず stderr へ出します。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createDailyServer } from "./dashboard.js";

const server = createDailyServer();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard-daily] stdio でリクエストを待機しています");
