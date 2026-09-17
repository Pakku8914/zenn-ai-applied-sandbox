/**
 * 社内お知らせ掲示板サーバー ― stdio トランスポートのエントリーポイント
 *
 * 実行： docker compose exec node npx tsx src/review02/q4-server.ts
 * （単体で起動すると stderr に 1 行出したあと沈黙します。それが正常です）
 *
 * stdout は JSON-RPC の通信路そのものなので console.log は絶対に使いません。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createNoticeServer } from "./q4-create-server.js";

const server = createNoticeServer();
await server.connect(new StdioServerTransport());

console.error("[notice-board] stdio でリクエストを待機しています");
