/**
 * チーム稼働ダッシュボード ― stdio トランスポートのエントリーポイント
 *
 * このファイルの仕事は「サーバー定義を stdio につなぐ」ことだけです。
 * ツールの実装はここに書きません（create-server.ts の責務）。
 *
 * 重要：stdio では標準出力（stdout）が JSON-RPC の通信路そのものです。
 * console.log を 1 回でも呼ぶと電文が壊れます。ログは必ず stderr へ。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createDashboardServer } from "./create-server.js";

const server = createDashboardServer();
const transport = new StdioServerTransport();
await server.connect(transport);

console.error("[team-dashboard] stdio でリクエストを待機しています");
