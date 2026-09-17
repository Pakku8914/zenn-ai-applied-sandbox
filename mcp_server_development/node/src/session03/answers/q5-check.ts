/**
 * 問題5 の解答：正常系と異常系をまとめて検証するクライアント
 *
 * サーバー定義（create-server.ts）を一切変更せずに、
 * 別のエントリーポイントから同じサーバーを起動して検証しています。
 * これが「定義とトランスポートを分離しておく」ことの実利です。
 *
 * このスクリプトはクライアント側なので console.log を使ってかまいません。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

type ToolResult = {
  isError?: boolean;
  content: Array<{ type: string; text?: string }>;
  [key: string]: unknown;
};

/** SDK の戻り値は型が緩いので、扱いやすい形に寄せる */
function asToolResult(value: unknown): ToolResult {
  return value as ToolResult;
}

let passed = 0;
let total = 0;

function check(label: string, ok: boolean): void {
  total += 1;
  if (ok) {
    passed += 1;
  }
  console.log(`${ok ? "PASS" : "FAIL"} ${label}`);
}

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/session03/server.ts"],
});
const client = new Client({ name: "q5-check", version: "1.0.0" });
await client.connect(transport);

// 1. ツール一覧
const { tools } = await client.listTools();
const names = tools.map((tool) => tool.name).sort();
check(
  "1. tools/list が 2 件（list_members, summarize_hours）",
  names.length === 2 && names[0] === "list_members" && names[1] === "summarize_hours",
);

// 2. 正常系
const normal = asToolResult(
  await client.callTool({
    name: "summarize_hours",
    arguments: { from: "2026-08-03", to: "2026-08-07" },
  }),
);
check("2. 正常系の集計が 56 時間", (normal.content[0]?.text ?? "").includes("合計 56 時間"));

// 3. 期間が逆順（ツール実行の失敗）
const reversed = asToolResult(
  await client.callTool({
    name: "summarize_hours",
    arguments: { from: "2026-08-07", to: "2026-08-03" },
  }),
);
check("3. 期間が逆順なら isError", reversed.isError === true);

// 4. 存在しないメンバー ID（ツール実行の失敗）
const unknownMember = asToolResult(
  await client.callTool({
    name: "summarize_hours",
    arguments: { from: "2026-08-03", to: "2026-08-07", memberId: "m-999" },
  }),
);
check("4. 存在しないメンバー ID なら isError", unknownMember.isError === true);

// 5. 日付形式違反（スキーマ違反 ―― SDK が isError を立てる）
const badFormat = asToolResult(
  await client.callTool({
    name: "summarize_hours",
    arguments: { from: "2026/08/03", to: "2026-08-07" },
  }),
);
check(
  "5. 日付形式違反は isError ＋ Input validation error",
  badFormat.isError === true &&
    (badFormat.content[0]?.text ?? "").includes("Input validation error"),
);

await client.close();

console.log(`${passed}/${total} PASS`);
if (passed !== total) {
  // process.exit() は出力が途中で切れることがあるため exitCode を設定して自然終了させる
  process.exitCode = 1;
}
