/**
 * 社内ドキュメント検索 MCP サーバー ― stdio エントリーポイント
 *
 * 実行：
 *   docker compose exec node npx tsx src/mid01/server.ts
 *   docker compose exec node npx tsx src/mid01/server.ts /tmp/mid01-docs
 *
 * このファイルの責務は「トランスポートを選んで繋ぐ」ことだけです。
 * ツールの登録は 1 行も書きません。セッション7 では、このファイルの隣に
 * http-server.ts を置き、create-server.ts を無変更のまま HTTP へ載せ替えます。
 *
 * stdout は JSON-RPC の通信路そのものなので console.log は絶対に使いません。
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { resolveDocsRoot } from "./config.js";
import { createDocSearchServer } from "./create-server.js";

const docsRoot = resolveDocsRoot();
const server = createDocSearchServer({ docsRoot });
await server.connect(new StdioServerTransport());

console.error(`[docsearch] stdio でリクエストを待機しています（docsRoot=${docsRoot}）`);
