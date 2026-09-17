/**
 * 問題4 の確認用クライアント
 *
 *   docker compose exec node npx tsx src/session06/answers/q4-verify.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

type ContentsLike = { uri: string; mimeType?: string; text?: string };

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/session06/answers/q4-server.ts"],
});
const client = new Client({ name: "q4-verify", version: "1.0.0" });
await client.connect(transport);

const ref = { type: "ref/resource" as const, uri: "glossary://{term}" };

const narrowed = await client.complete({ ref, argument: { name: "term", value: "s" } });
console.log(`[1/4] 補完（term="s"）: ${narrowed.completion.values.join(", ")}`);

const all = await client.complete({ ref, argument: { name: "term", value: "" } });
console.log(
  `[2/4] 補完（term=""）: ${all.completion.values.length} 件 / 先頭3件=${all.completion.values
    .slice(0, 3)
    .join(", ")}`,
);

const aliased = await client.readResource({ uri: "glossary://sp" });
const head = (aliased.contents as ContentsLike[])[0];
console.log(
  `[3/4] glossary://sp: uri=${head?.uri} / 1行目=${(head?.text ?? "").split("\n")[0]}`,
);

try {
  await client.readResource({ uri: "glossary://SP" });
  console.log("[4/4] glossary://SP: 読めてしまいました（想定外）");
} catch (error) {
  const message = (error as Error).message;
  console.log(
    `[4/4] glossary://SP: code=${(error as { code?: number }).code}` +
      ` / メッセージに入力を含まない=${!message.includes("SP")}`,
  );
}

await client.close();
console.log("OK: 別名の補完と解決が一致しています");
