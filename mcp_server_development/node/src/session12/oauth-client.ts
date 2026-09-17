/**
 * 端から端まで通す検証クライアント
 *
 *   docker compose exec node npx tsx src/session12/oauth-client.ts
 *   docker compose exec node npx tsx src/session12/oauth-client.ts \
 *     --scope "docs:read docs:admin" --call reindex_documents
 *   docker compose exec node npx tsx src/session12/oauth-client.ts --call reindex_documents
 *     → docs:read だけのトークンで管理ツールを呼ぼうとする実験
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import { obtainAccessToken } from "./oauth-flow.js";
import { SCOPE_DOCS_READ } from "./scopes.js";

const flags = new Map<string, string>();
const argv = process.argv.slice(2);
for (let index = 0; index < argv.length; index += 1) {
  const key = argv[index];
  if (key === undefined || !key.startsWith("--")) {
    continue;
  }
  const value = argv[index + 1];
  flags.set(key.slice(2), value === undefined || value.startsWith("--") ? "true" : value);
  if (value !== undefined && !value.startsWith("--")) {
    index += 1;
  }
}

const mcpUrl = flags.get("url") ?? "http://127.0.0.1:3939/mcp";
const scope = flags.get("scope") ?? SCOPE_DOCS_READ;
const token = await obtainAccessToken({ mcpUrl, scope, resource: flags.get("resource") });
for (const step of token.steps) {
  console.log(step);
}
if (flags.get("print-token") === "true") {
  // 全体は出さない。先頭だけでも「JWT の形をしている」ことは確認できる
  console.log(`[token] ${token.accessToken.slice(0, 32)}…（以降は表示しません）`);
}

const transport = new StreamableHTTPClientTransport(new URL(mcpUrl), {
  // ★ すべてのリクエストに Authorization を付ける。
  //   オプション名は SDK の版で変わりうるので、型定義で確認してください（実行準備の 4）
  requestInit: { headers: { authorization: `Bearer ${token.accessToken}` } },
});
const client = new Client({ name: "session12-oauth-client", version: "1.0.0" });

await client.connect(transport);
const info = client.getServerVersion();
console.log(`[7/9] 接続: ${info?.name} v${info?.version} / Mcp-Session-Id: ${transport.sessionId ?? "(なし)"}`);

const { tools } = await client.listTools();
console.log(`[8/9] tools/list（付与スコープ: ${token.scope}）: ${tools.map((tool) => tool.name).join(", ")}`);

const call = flags.get("call");
if (call !== undefined && call !== "true") {
  const result = (await client.callTool({
    name: call,
    arguments: call === "search_documents" ? { query: "VPN", limit: 2 } : {},
  })) as { isError?: boolean; content?: { text?: string }[] };
  const text = result.content?.[0]?.text ?? "(本文なし)";
  console.log(`[9/9] tools/call ${call}: isError=${result.isError === true}`);
  console.log(text);
} else {
  console.log("[9/9] tools/call は省略しました（--call <ツール名> で実行できます）");
}

await transport.terminateSession();
await client.close();
