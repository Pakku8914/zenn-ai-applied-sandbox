/**
 * ❌ 悪い例：stdio サーバーが stdout に書いている
 *
 * 実験専用のファイルです。真似しないでください。
 * mid01 のサーバー定義はそのまま使い、最後の 1 行だけを間違えています。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { resolveDocsRoot } from "../mid01/config.js";
import { createDocSearchServer } from "../mid01/create-server.js";

const docsRoot = resolveDocsRoot([]);
const server = createDocSearchServer({ docsRoot });
await server.connect(new StdioServerTransport());

// ❌ ここが罠。stdout は JSON-RPC の通信路なので、この 1 行が電文を壊す
console.log(`[bad] docsRoot=${docsRoot} で待機しています`);
