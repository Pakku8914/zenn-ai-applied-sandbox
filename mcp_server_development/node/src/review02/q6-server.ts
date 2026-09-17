/**
 * 問題6 のサーバー ― stdio トランスポートのエントリーポイント
 *
 * 実行： docker compose exec node npx tsx src/review02/q6-server.ts
 * 事前に q6-setup.ts を実行して公開ディレクトリを作ってください。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createNoticeFileServer } from "./q6-create-server.js";

const server = createNoticeFileServer();
await server.connect(new StdioServerTransport());

console.error("[notice-files] stdio でリクエストを待機しています");
