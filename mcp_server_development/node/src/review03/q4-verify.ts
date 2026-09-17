/**
 * 問題4 の解答 ―― SDK クライアントでつなぐ確認用スクリプト
 *
 *   docker compose exec node npx tsx src/review03/q4-verify.ts
 *
 * クライアント側なので console.log を使ってかまいません
 * （禁止されるのは「サーバープロセスの stdout」だけです）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { McpError } from "@modelcontextprotocol/sdk/types.js";

type SearchStructured = {
  totalMatched: number;
  returned: number;
  truncated: boolean;
  results: { path: string; uri: string; title: string }[];
};

const url = new URL(process.argv[2] ?? "http://127.0.0.1:3939/mcp");
const transport = new StreamableHTTPClientTransport(url);
const client = new Client({ name: "review03-q4-verify", version: "1.0.0" });

await client.connect(transport);
const info = client.getServerVersion();
console.log(`[1/8] 接続: ${info?.name} v${info?.version} / URL=${url.href}`);
// セッション ID はトランスポートが応答ヘッダーから拾って保持している
console.log(`[2/8] Mcp-Session-Id: ${transport.sessionId ?? "(なし＝ステートレス運用)"}`);

const caps = client.getServerCapabilities();
const has = (value: unknown): string => (value === undefined ? "なし" : "あり");
console.log(
  `[3/8] ケイパビリティ: tools=${has(caps?.tools)} / resources=${has(caps?.resources)}` +
    ` / prompts=${has(caps?.prompts)} / completions=${has(caps?.completions)}`,
);

const { tools } = await client.listTools();
const search = tools.find((tool) => tool.name === "search_documents");
console.log(
  `[4/8] tools/list: ${tools.map((tool) => tool.name).join(", ")}` +
    ` / readOnlyHint=${search?.annotations?.readOnlyHint}` +
    ` / openWorldHint=${search?.annotations?.openWorldHint}`,
);

const result = await client.callTool({
  name: "search_documents",
  arguments: { query: "VPN", limit: 2 },
});
const structured = result.structuredContent as SearchStructured;
const kinds = (result.content as { type: string }[]).map((block) => block.type).join(",");
console.log(
  `[5/8] query="VPN" limit=2: totalMatched=${structured.totalMatched}` +
    ` returned=${structured.returned} truncated=${structured.truncated} / 種別=${kinds}`,
);

let readOk = 0;
let firstLine = "";
for (const hit of structured.results) {
  const read = await client.readResource({ uri: hit.uri });
  const first = read.contents[0] as { text?: string } | undefined;
  if (typeof first?.text === "string") {
    readOk += 1;
    if (firstLine === "") {
      firstLine = first.text.split("\n")[0] ?? "";
    }
  }
}
console.log(
  `[6/8] resource_link を全部読む: ${readOk}/${structured.results.length} 件成功 / 1行目=${firstLine}`,
);

/** 攻撃 URI を投げてエラーコードだけを取り出す（入力値はログに残さない） */
const codeOf = async (uri: string): Promise<number | string> => {
  try {
    await client.readResource({ uri });
    return "拒否されなかった";
  } catch (error) {
    return error instanceof McpError ? error.code : "不明";
  }
};
console.log(
  `[7/8] 攻撃 3 件: 相対パス=${await codeOf("docs://..%2f..%2f..%2fetc%2fpasswd")}` +
    ` / 絶対パス=${await codeOf("docs://%2fetc%2fpasswd")}` +
    ` / 二重エンコード=${await codeOf("docs://%252e%252e%252fetc%252fpasswd")}`,
);

// DELETE を送ってセッションを明示的に破棄する（送らないとサーバー側に残る）
await transport.terminateSession();
console.log(`[8/8] terminateSession 後: sessionId=${transport.sessionId ?? "(破棄済み)"}`);
await client.close();
console.log("OK: サーバー定義を 1 行も変えずに Streamable HTTP で公開できました");
