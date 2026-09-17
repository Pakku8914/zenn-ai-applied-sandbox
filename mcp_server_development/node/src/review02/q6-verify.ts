/**
 * 問題6 の確認用クライアント ― MCP 経由でも外に出られないことを確かめる
 *
 *   docker compose exec node npx tsx src/review02/q6-setup.ts
 *   docker compose exec node npx tsx src/review02/q6-verify.ts
 *
 * 攻撃 URI が「読めなかった」ことだけでなく、万一読めた場合に
 * 中身が公開ディレクトリの外のものであることも検出します。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

type ContentsLike = { uri: string; mimeType?: string; text?: string };

function firstContents(result: { contents: unknown[] }): ContentsLike {
  const [head] = result.contents as ContentsLike[];
  if (head === undefined) {
    throw new Error("contents が空です");
  }
  return head;
}

function firstLine(text: string): string {
  return text.split("\n")[0] ?? "";
}

function errorCodeOf(error: unknown): number | undefined {
  return (error as { code?: number }).code;
}

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/review02/q6-server.ts"],
});
const client = new Client({ name: "review02-q6-verify", version: "1.0.0" });
await client.connect(transport);

const info = client.getServerVersion();
const templates = await client.listResourceTemplates();
console.log(
  `[1/4] 接続: ${info?.name} v${info?.version}` +
    ` / resources/templates/list=${templates.resourceTemplates.length} 件` +
    ` → ${templates.resourceTemplates.map((template) => template.uriTemplate).join(", ")}`,
);

const candidates = await client.complete({
  ref: { type: "ref/resource", uri: "notice-file://{name}" },
  argument: { name: "name", value: "" },
});
console.log(`[2/4] 補完（name=""）: ${candidates.completion.values.join(", ")}`);

const normal = firstContents(await client.readResource({ uri: "notice-file://fire-drill.md" }));
console.log(
  `[3/4] notice-file://fire-drill.md: mimeType=${normal.mimeType}` +
    ` / 1行目=${firstLine(normal.text ?? "")}`,
);

const results: string[] = [];
for (const [label, uri] of [
  ["相対パス", "notice-file://..%2f..%2f..%2fetc%2fpasswd"],
  ["絶対パス", "notice-file://%2fetc%2fpasswd"],
  ["二重エンコード", "notice-file://%252e%252e%252f%252e%252e%252fetc%252fpasswd"],
  ["シンボリックリンク", "notice-file://staff-only.md"],
] as const) {
  try {
    const leaked = firstContents(await client.readResource({ uri }));
    results.push(`${label}=読めてしまった（先頭12文字=${(leaked.text ?? "").slice(0, 12)}）`);
  } catch (error) {
    results.push(`${label}=${errorCodeOf(error)}`);
  }
}
console.log(`[4/4] 攻撃 4 件: ${results.join(" / ")}`);

await client.close();
console.log("OK: 公開ディレクトリの外には 1 件も到達していません");
