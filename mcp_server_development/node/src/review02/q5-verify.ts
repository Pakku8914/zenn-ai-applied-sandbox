/**
 * 問題5 の確認用クライアント
 *
 *   docker compose exec node npx tsx src/review02/q5-verify.ts
 *
 * 「補完は候補を返すだけ」「検証は候補外を弾く」の 2 つが別の仕組みであることを、
 * 同じ引数に対する 2 つの結果として確認します。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

type MessageLike = {
  role: string;
  content: {
    type: string;
    text?: string;
    resource?: { uri: string; mimeType?: string; text?: string };
  };
};

function messagesOf(result: { messages: unknown[] }): MessageLike[] {
  return result.messages as MessageLike[];
}

function errorCodeOf(error: unknown): number | undefined {
  return (error as { code?: number }).code;
}

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/review02/q5-server.ts"],
});
const client = new Client({ name: "review02-q5-verify", version: "1.0.0" });
await client.connect(transport);

const prompts = await client.listPrompts();
const digest = prompts.prompts.find((prompt) => prompt.name === "notice_digest");
const args = [...(digest?.arguments ?? [])].sort((a, b) => a.name.localeCompare(b.name));
console.log(
  `[1/6] prompts/list: ${digest?.name}` +
    ` / 引数=${args.map((argument) => argument.name).join(", ")}` +
    ` / 必須=${args
      .filter((argument) => argument.required === true)
      .map((argument) => argument.name)
      .join(", ")}`,
);

const allCategories = await client.complete({
  ref: { type: "ref/prompt", name: "notice_digest" },
  argument: { name: "category", value: "" },
});
console.log(`[2/6] 補完（category=""）: ${allCategories.completion.values.join(", ")}`);

const narrowed = await client.complete({
  ref: { type: "ref/prompt", name: "notice_digest" },
  argument: { name: "category", value: "f" },
});
console.log(`[3/6] 補完（category="f"）: ${narrowed.completion.values.join(", ")}`);

const inlined = messagesOf(
  await client.getPrompt({
    name: "notice_digest",
    arguments: { query: "ネットワーク", category: "all", attach: "inline" },
  }),
);
const attachment = inlined[1]?.content;
console.log(
  `[4/6] attach=inline: messages=${inlined.length}` +
    ` / 種別=${inlined.map((message) => message.content.type).join(",")}` +
    ` / mimeType=${attachment?.resource?.mimeType} / uri=${attachment?.resource?.uri}`,
);

const linked = messagesOf(
  await client.getPrompt({
    name: "notice_digest",
    arguments: { query: "ネットワーク", category: "all", attach: "link" },
  }),
);
console.log(
  `[5/6] attach=link: messages=${linked.length}` +
    ` / 種別=${linked.map((message) => message.content.type).join(",")}`,
);

const empty = messagesOf(
  await client.getPrompt({
    name: "notice_digest",
    arguments: { query: "リモートワーク", category: "all", attach: "inline" },
  }),
);
const codes: string[] = [];
for (const [label, promptArguments] of [
  ["category=sales", { query: "ネットワーク", category: "sales", attach: "inline" }],
  ["attach=pdf", { query: "ネットワーク", category: "all", attach: "pdf" }],
] as const) {
  try {
    await client.getPrompt({ name: "notice_digest", arguments: promptArguments });
    codes.push(`${label}=通ってしまった`);
  } catch (error) {
    codes.push(`${label} → ${errorCodeOf(error)}`);
  }
}
console.log(
  `[6/6] 0 件: messages=${empty.length}` +
    ` ／ ${codes[0] ?? ""}（自分で書いた検証）/ ${codes[1] ?? ""}（SDK の検証）`,
);

await client.close();
console.log("OK: 補完は候補を返し、検証は候補外を拒否しています");
