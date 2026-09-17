/**
 * 配布物から起動したサーバーに MCP クライアントとして話しかける
 *
 *   docker compose exec node npx tsx src/session14/probe-stdio.ts docsearch-mcp --docs-root /app/src/session14/sample-docs
 *   docker compose exec -e DOCSEARCH_ROOT=/app/src/session14/sample-docs node npx tsx src/session14/probe-stdio.ts docsearch-mcp
 *
 * 第 1 引数がコマンド、以降が引数です。ホストが渡すのと同じ command / args / env の形に
 * そろえてあるので、「ホスト設定ファイルに書く内容」をそのまま試せます。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const [command, ...args] = process.argv.slice(2);
if (command === undefined) {
  console.error("使い方: npx tsx src/session14/probe-stdio.ts <コマンド> [引数...]");
  process.exit(2);
}

/**
 * 環境変数は子プロセスへ自動では渡りません。SDK は安全な一部だけを引き継ぐので、
 * サーバーに渡したい変数は明示します（ホスト設定の env がこれに相当します）。
 */
const docsRoot = process.env["DOCSEARCH_ROOT"];
const transport = new StdioClientTransport({
  command,
  args,
  ...(docsRoot === undefined
    ? {}
    : {
        env: {
          PATH: process.env["PATH"] ?? "",
          HOME: process.env["HOME"] ?? "",
          DOCSEARCH_ROOT: docsRoot,
        },
      }),
});

const client = new Client({ name: "session14-probe", version: "1.0.0" });
await client.connect(transport);

console.log(`[probe] 起動コマンド: ${[command, ...args].join(" ")}`);
const info = client.getServerVersion();
console.log(`[probe] serverInfo: ${info?.name} v${info?.version}`);

const { tools } = await client.listTools();
console.log(`[probe] tools: ${tools.map((tool) => tool.name).join(", ")}`);

const result = await client.callTool({
  name: "search_documents",
  arguments: { query: "VPN" },
});
const structured = result.structuredContent as
  | { totalMatched?: number; results?: Array<{ path: string }> }
  | undefined;
console.log(
  `[probe] search_documents("VPN"): totalMatched=${structured?.totalMatched}` +
    ` / 先頭=${structured?.results?.[0]?.path}`,
);

await client.close();
console.log("OK: 配布物から起動したサーバーが MCP として応答しました");
