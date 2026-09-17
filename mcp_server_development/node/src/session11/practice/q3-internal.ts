/**
 * 問題3 の解答：想定外の例外を遮断する
 *
 * 実行： docker compose exec node npx tsx src/session11/practice/q3-internal.ts
 *
 * SDK は「ハンドラが投げた例外」を自動で isError: true のツール結果に変換します。
 * つまり包まなくても isError は立ちます。違うのは「何が書かれているか」です。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { internalFailure, leaksInternalDetail, toolFailure } from "../errors.js";

/** ツール結果のうち、この問題で扱う形 */
type TextResult = { content: Array<{ type: "text"; text: string }>; isError?: boolean };

/**
 * ハンドラを包み、想定外の例外を「返してよい形」に変換する。
 *
 * ポイントは 2 つです。
 *   ① 例外の詳細は internalFailure() の中で stderr にだけ出る
 *   ② 返るのは参照番号つきの 3 行だけ（内部パス・トークンは含まれない）
 */
function safeTool<A>(
  context: string,
  handler: (args: A) => Promise<TextResult>,
): (args: A) => Promise<TextResult> {
  return async (args: A): Promise<TextResult> => {
    try {
      return await handler(args);
    } catch (error) {
      return toolFailure(internalFailure(context, error));
    }
  };
}

/** 想定外の例外を再現する。内部パスとトークンの断片をあえて含める */
function explode(): never {
  throw new Error(
    "ENOENT: no such file or directory, open '/app/src/session11/practice/secret.json' (token=svc_secret_abcd)",
  );
}

const server = new McpServer({ name: "practice-q3", version: "1.0.0" });

server.registerTool(
  "boom",
  {
    title: "包まない版",
    description: "必ず例外を投げます（比較用）。",
    inputSchema: { label: z.string().optional().describe("使いません") },
  },
  // 式の形で書きます。ブロックで書くと戻り値の型が void になり型エラーになります
  async () => explode(),
);

server.registerTool(
  "safe_boom",
  {
    title: "包んだ版",
    description: "同じ例外を safeTool() で包んで返します。",
    inputSchema: { label: z.string().optional().describe("使いません") },
  },
  safeTool("safe_boom", async () => explode()),
);

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "practice-q3", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

for (const name of ["boom", "safe_boom"] as const) {
  const result = await client.callTool({ name, arguments: {} });
  const text = (result.content as Array<{ text?: string }> | undefined)?.[0]?.text ?? "";
  console.log(
    `[${name.padEnd(9)}] isError=${String(result.isError === true).padEnd(5)} ` +
      `chars=${String(text.length).padStart(4)} ` +
      `内部情報の露出=${leaksInternalDetail(text) ? "あり" : "なし"} ` +
      `参照番号=${/E-\d{3}/.test(text) ? "あり" : "なし"}`,
  );
}

console.log("stderr に詳細が出ていることを確認してください（[internal] E-001 ...）");

await client.close();
await server.close();
