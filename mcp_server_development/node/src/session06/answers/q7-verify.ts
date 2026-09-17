/**
 * 問題7 の確認用クライアント（TypeScript 側）
 *
 *   docker compose exec node npx tsx src/session06/answers/q7-verify.ts
 *
 * Python 側（q7_verify.py）と同じ 3 項目を出力します。
 */
import { createHash } from "node:crypto";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const URI = "report://excel/2026-08-03_2026-08-07.csv";

type ContentsLike = { uri: string; mimeType?: string; blob?: string };

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/session06/server.ts"],
});
const client = new Client({ name: "q7-verify", version: "1.0.0" });
await client.connect(transport);

const result = await client.readResource({ uri: URI });
const head = (result.contents as ContentsLike[])[0];
const blob = head?.blob ?? "";
const digest = createHash("sha256").update(blob, "ascii").digest("hex").slice(0, 16);
const text = Buffer.from(blob, "base64").toString("utf16le").replace(/^﻿/, "");

console.log(`[TypeScript] mimeType = ${head?.mimeType}`);
console.log(`[TypeScript] base64 の長さ = ${blob.length}`);
console.log(`[TypeScript] base64 の先頭 4 文字 = ${blob.slice(0, 4)}`);
console.log(`[TypeScript] SHA-256（先頭 16 桁） = ${digest}`);
console.log(`[TypeScript] デコード後の 1 行目 = ${text.split("\n")[0]}`);
console.log(`[TypeScript] デコード後の行数 = ${text.trimEnd().split("\n").length}`);

await client.close();
