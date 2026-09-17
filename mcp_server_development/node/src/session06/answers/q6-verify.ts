/**
 * 問題6 の確認用クライアント
 *
 *   docker compose exec node npx tsx src/session06/answers/q6-verify.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

type MessageLike = {
  content: { type: string; text?: string; resource?: { uri: string; mimeType?: string } };
};

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/session06/answers/q6-server.ts"],
});
const client = new Client({ name: "q6-verify", version: "1.0.0" });
await client.connect(transport);

const { prompts } = await client.listPrompts();
const target = prompts.find((prompt) => prompt.name === "member_report_draft");
console.log(
  `[1/4] prompts/list: ${target?.name} / 引数=${(target?.arguments ?? [])
    .map((argument) => `${argument.name}(${argument.required === true ? "必須" : "任意"})`)
    .sort((a, b) => a.localeCompare(b))
    .join(", ")}`,
);

const candidates = await client.complete({
  ref: { type: "ref/prompt", name: "member_report_draft" },
  argument: { name: "member_id", value: "m-0" },
});
console.log(`[2/4] 補完（member_id="m-0"）: ${candidates.completion.values.join(", ")}`);

const withGlossary = await client.getPrompt({
  name: "member_report_draft",
  arguments: { member_id: "m-003", week_start: "2026-08-03", include_glossary: "true" },
});
const without = await client.getPrompt({
  name: "member_report_draft",
  arguments: { member_id: "m-003", week_start: "2026-08-03" },
});
const blocks = withGlossary.messages as MessageLike[];
console.log(
  `[3/4] include_glossary=true: messages=${blocks.length}` +
    ` / 種別=${blocks.map((block) => block.content.type).join(",")}` +
    ` / mimeType=${blocks
      .map((block) => block.content.resource?.mimeType)
      .filter((mimeType) => mimeType !== undefined)
      .join(",")}` +
    ` ／ 省略時: messages=${without.messages.length}`,
);

try {
  await client.getPrompt({
    name: "member_report_draft",
    arguments: { member_id: "m-999", week_start: "2026-08-03" },
  });
  console.log("[4/4] 存在しない member_id: 成功してしまいました（想定外）");
} catch (error) {
  console.log(`[4/4] 存在しない member_id: code=${(error as { code?: number }).code}`);
}

await client.close();
console.log("OK: 引数付きプロンプトが仕様どおりに応答しています");
