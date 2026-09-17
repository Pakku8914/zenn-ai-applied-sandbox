/**
 * 問題1 の解答：stdio エントリーポイント
 * 中身（q1-create-server.ts）を差し替えるだけで、この 4 行は変わりません。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createDashboardServerQ1 } from "./q1-create-server.js";

const server = createDashboardServerQ1();
await server.connect(new StdioServerTransport());

console.error("[team-dashboard] stdio でリクエストを待機しています");
