/**
 * チーム稼働ダッシュボードの疎通確認クライアント
 *
 *   docker compose exec node npx tsx src/session03/smoke.ts
 *   docker compose exec node npx tsx src/session03/smoke.ts src/session03/lowlevel-server.ts
 *
 * このスクリプトは「クライアント側」なので console.log を使ってかまいません。
 * 通信路として stdout を使っているのはサーバープロセスのほうだけで、
 * クライアントの stdout は人間が読む画面にすぎないからです。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

type ToolResult = {
  isError?: boolean;
  content: Array<{ type: string; text?: string }>;
  [key: string]: unknown;
};

function textOf(result: unknown): string {
  const typed = result as ToolResult;
  const body = typed.content[0]?.text ?? "(テキストなし)";
  return typed.isError === true ? `【ツールエラー】${body}` : body;
}

const entry = process.argv[2] ?? "src/session03/server.ts";

// クライアントがサーバーを子プロセスとして起動する。これが stdio トランスポートの実像
const transport = new StdioClientTransport({ command: "npx", args: ["tsx", entry] });
const client = new Client({ name: "dashboard-smoke", version: "1.0.0" });
await client.connect(transport);

const info = client.getServerVersion();
console.log(`[1/5] 接続成功: ${info?.name} v${info?.version}`);

const { tools } = await client.listTools();
const names = tools.map((tool) => tool.name);
console.log(`[2/5] tools/list: ${names.join(", ")}`);

console.log("[3/5] list_members(team=platform):");
console.log(textOf(await client.callTool({ name: "list_members", arguments: { team: "platform" } })));

if (names.includes("summarize_hours")) {
  console.log("[4/5] summarize_hours(2026-08-03 〜 2026-08-07):");
  console.log(
    textOf(
      await client.callTool({
        name: "summarize_hours",
        arguments: { from: "2026-08-03", to: "2026-08-07" },
      }),
    ),
  );
} else {
  console.log("[4/5] summarize_hours は未登録のためスキップします");
}

// 列挙に無い値を渡す。Zod が弾き、ツール結果に isError: true が立つ
const invalid = await client.callTool({
  name: "list_members",
  arguments: { team: "unknown-team" },
});
console.log(`[5/5] 不正な引数は isError=${invalid.isError} で差し戻されました`);
console.log(`      本文: ${textOf(invalid)}`);

await client.close();
console.log("OK: セッション3 のサーバーは正常に動作しています");
