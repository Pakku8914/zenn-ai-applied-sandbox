/**
 * セッション9 のサーバー ―― stdio エントリーポイント
 *
 *   docker compose exec node npx tsx src/session09/server.ts
 *
 * stdout は JSON-RPC の通信路そのものなので console.log は使いません。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { resolveDocsRoot } from "../mid01/config.js";
import { createSession09Server } from "./create-server.js";

const docsRoot = resolveDocsRoot();
const server = createSession09Server({ docsRoot });
await server.connect(new StdioServerTransport());

console.error(`[session09] stdio で待機しています（docsRoot=${docsRoot}）`);
