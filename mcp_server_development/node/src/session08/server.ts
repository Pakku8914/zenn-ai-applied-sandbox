/**
 * 気象観測データ MCP サーバー（stdio エントリーポイント）
 *
 * 実行： docker compose exec node npx tsx src/session08/server.ts
 * （単体で起動すると stderr に 1 行出したあと沈黙します。それが正常です）
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createServer } from "./create-server.js";

const server = createServer();
await server.connect(new StdioServerTransport());

// ログは stderr へ。stdout は JSON-RPC 専用なので絶対に汚さない
console.error("[weather-observations] stdio で待機しています");
