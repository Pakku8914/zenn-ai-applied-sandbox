/**
 * 問題5 の確認用クライアント
 *
 *   docker compose exec node npx tsx src/session06/answers/q5-verify.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import {
  ResourceUpdatedNotificationSchema,
  ToolListChangedNotificationSchema,
} from "@modelcontextprotocol/sdk/types.js";

const updated: string[] = [];
let toolListChanged = 0;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function trySubscribe(client: Client, uri: string): Promise<string> {
  try {
    await client.subscribeResource({ uri });
    return "OK";
  } catch (error) {
    return String((error as { code?: number }).code);
  }
}

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/session06/answers/q5-server.ts"],
});
const client = new Client({ name: "q5-verify", version: "1.0.0" });
client.setNotificationHandler(ResourceUpdatedNotificationSchema, async (notification) => {
  updated.push(notification.params.uri);
});
client.setNotificationHandler(ToolListChangedNotificationSchema, async () => {
  toolListChanged += 1;
});
await client.connect(transport);

// 索引だけを購読する（集計リソースは購読しない）
const indexResult = await trySubscribe(client, "glossary://index");
const templateResult = await trySubscribe(client, "report://weekly/{period}.csv");
console.log(`[1/5] 購読: glossary://index=${indexResult} / テンプレート URI=${templateResult}`);

const added = (await client.callTool({
  name: "add_glossary_term",
  arguments: {
    slug: "burndown",
    term: "バーンダウン",
    category: "指標",
    definition: "残作業量の推移を表すグラフ。",
  },
})) as { structuredContent?: { termCount?: number; notified?: boolean } };
await sleep(100);
console.log(
  `[2/5] 用語追加: termCount=${added.structuredContent?.termCount}` +
    ` / notified=${added.structuredContent?.notified} / updated=${updated.length} 件（${updated.join(", ")}）`,
);

const duplicated = (await client.callTool({
  name: "add_glossary_term",
  arguments: {
    slug: "burndown",
    term: "バーンダウン",
    category: "指標",
    definition: "重複登録の確認。",
  },
})) as { isError?: boolean; [key: string]: unknown };
await sleep(100);
console.log(
  `[3/5] 重複追加: isError=${duplicated.isError === true} / updated=${updated.length} 件（増えない）`,
);

const workLog = (await client.callTool({
  name: "add_work_log",
  arguments: { memberId: "m-003", projectId: "p-report", date: "2026-08-07", hours: 3 },
})) as { structuredContent?: { notified?: boolean } };
await sleep(100);
console.log(
  `[4/5] 未購読の add_work_log: notified=${workLog.structuredContent?.notified}` +
    ` / updated=${updated.length} 件（増えない）`,
);

await client.callTool({ name: "set_maintenance_mode", arguments: { enabled: true } });
await sleep(100);
const { tools } = await client.listTools();
console.log(
  `[5/5] メンテナンス中の tools=${tools.length} 本（${tools
    .map((tool) => tool.name)
    .sort((a, b) => a.localeCompare(b))
    .join(", ")}）/ tools/list_changed=${toolListChanged} 件`,
);

await client.close();
console.log("OK: 3 種類の通知を条件どおりに送り分けています");
