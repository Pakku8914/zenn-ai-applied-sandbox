/**
 * 問題5 のサーバー ― stdio トランスポートのエントリーポイント
 *
 * 実行： docker compose exec node npx tsx src/review02/q5-server.ts
 * ログは stderr へ（stdout は JSON-RPC の通信路）。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createNoticeServerQ5 } from "./q5-create-server.js";

const server = createNoticeServerQ5();
await server.connect(new StdioServerTransport());

console.error("[notice-board] stdio でリクエストを待機しています");
