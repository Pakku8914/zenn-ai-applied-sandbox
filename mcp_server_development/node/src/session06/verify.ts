/**
 * セッション6 の確認用クライアント
 *
 *   docker compose exec node npx tsx src/session06/verify.ts
 *
 * このスクリプトはクライアント側なので console.log を使ってかまいません
 * （禁止されているのは「サーバープロセスの stdout」だけです）。
 *
 * 出力が実行するたびに変わらないよう、時刻に依存する値は出力していません。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import {
  ResourceListChangedNotificationSchema,
  ResourceUpdatedNotificationSchema,
} from "@modelcontextprotocol/sdk/types.js";

type ContentsLike = { uri: string; mimeType?: string; text?: string; blob?: string };
type MessageLike = {
  role: string;
  content: {
    type: string;
    text?: string;
    resource?: { uri: string; mimeType?: string; text?: string };
  };
};

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

/** 末尾の改行を数えないようにしてから行数を数える */
function lineCount(text: string): number {
  return text.trimEnd().split("\n").length;
}

function errorCodeOf(error: unknown): number | undefined {
  return (error as { code?: number }).code;
}

/** 通知が届くのを待つ（stdio は順序が保証されますが、念のため間を置きます） */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const updatedUris: string[] = [];
let listChangedCount = 0;

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/session06/server.ts"],
});
const client = new Client({ name: "session06-verify", version: "1.0.0" });

// 通知ハンドラは接続前に登録する（接続後だと最初の通知を取りこぼす可能性があります）
client.setNotificationHandler(ResourceUpdatedNotificationSchema, async (notification) => {
  updatedUris.push(notification.params.uri);
});
client.setNotificationHandler(ResourceListChangedNotificationSchema, async () => {
  listChangedCount += 1;
});

await client.connect(transport);

const info = client.getServerVersion();
const capabilities = client.getServerCapabilities();
console.log(
  `[1/14] 接続: ${info?.name} v${info?.version}` +
    ` / resources.subscribe=${capabilities?.resources?.subscribe === true}` +
    ` / resources.listChanged=${capabilities?.resources?.listChanged === true}` +
    ` / completions=${capabilities?.completions !== undefined}` +
    ` / prompts=${capabilities?.prompts !== undefined}`,
);

const listed = await client.listResources();
console.log(
  `[2/14] resources/list: ${listed.resources.length} 件 → ${listed.resources.map((resource) => resource.uri).join(", ")}`,
);

const templates = await client.listResourceTemplates();
console.log(
  `[3/14] resources/templates/list: ${templates.resourceTemplates.length} 件 → ${templates.resourceTemplates
    .map((template) => template.uriTemplate)
    .sort((a, b) => a.localeCompare(b))
    .join(", ")}`,
);

const summary = firstContents(await client.readResource({ uri: "dashboard://summary/current" }));
const snapshot = JSON.parse(summary.text ?? "{}") as {
  revision: number;
  totalHours: number;
  memberCount: number;
};
console.log(
  `[4/14] summary: mimeType=${summary.mimeType} / revision=${snapshot.revision}` +
    ` / totalHours=${snapshot.totalHours} / memberCount=${snapshot.memberCount}`,
);

const term = firstContents(await client.readResource({ uri: "glossary://sprint" }));
console.log(
  `[5/14] glossary://sprint: mimeType=${term.mimeType} / 行数=${lineCount(term.text ?? "")}` +
    ` / 1行目=${firstLine(term.text ?? "")}`,
);

const narrowed = await client.complete({
  ref: { type: "ref/resource", uri: "glossary://{term}" },
  argument: { name: "term", value: "c" },
});
console.log(
  `[6/14] 補完（term="c"）: ${narrowed.completion.values.join(", ")}` +
    ` / total=${narrowed.completion.total} / hasMore=${narrowed.completion.hasMore === true}`,
);

const all = await client.complete({
  ref: { type: "ref/resource", uri: "glossary://{term}" },
  argument: { name: "term", value: "" },
});
console.log(
  `[7/14] 補完（term=""）: ${all.completion.values.length} 件` +
    ` / 先頭3件=${all.completion.values.slice(0, 3).join(", ")}`,
);

const weekly = firstContents(
  await client.readResource({ uri: "report://weekly/2026-08-03_2026-08-07.csv" }),
);
console.log(
  `[8/14] report://weekly/2026-08-03_2026-08-07.csv: mimeType=${weekly.mimeType}` +
    ` / 行数=${lineCount(weekly.text ?? "")} / バイト数=${Buffer.byteLength(weekly.text ?? "", "utf8")}` +
    ` / 1行目=${firstLine(weekly.text ?? "")}`,
);

const excel = firstContents(
  await client.readResource({ uri: "report://excel/2026-08-03_2026-08-07.csv" }),
);
const decoded = Buffer.from(excel.blob ?? "", "base64").toString("utf16le");
const hasBom = decoded.charCodeAt(0) === 0xfeff;
const excelBody = hasBom ? decoded.slice(1) : decoded;
console.log(
  `[9/14] report://excel/2026-08-03_2026-08-07.csv: mimeType=${excel.mimeType}` +
    ` / text は空=${excel.text === undefined} / BOM=${hasBom} / 1行目=${firstLine(excelBody)}`,
);

const prompts = await client.listPrompts();
const prompt = prompts.prompts[0];
console.log(
  `[10/14] prompts/list: ${prompt?.name} / 引数=${(prompt?.arguments ?? [])
    .map((argument) => argument.name)
    .sort((a, b) => a.localeCompare(b))
    .join(", ")}`,
);

const draft = await client.getPrompt({
  name: "weekly_report_draft",
  arguments: { week_start: "2026-08-03", week_end: "2026-08-07", audience: "manager" },
});
const messages = draft.messages as MessageLike[];
console.log(
  `[11/14] prompts/get: messages=${messages.length} / 1件目=${messages[0]?.content.type}` +
    ` / 2件目=${messages[1]?.content.type}（mimeType=${messages[1]?.content.resource?.mimeType}）`,
);

const withContext = await client.complete({
  ref: { type: "ref/prompt", name: "weekly_report_draft" },
  argument: { name: "week_end", value: "" },
  context: { arguments: { week_start: "2026-08-03" } },
});
const withoutContext = await client.complete({
  ref: { type: "ref/prompt", name: "weekly_report_draft" },
  argument: { name: "week_end", value: "" },
});
console.log(
  `[12/14] 補完（week_end / context に week_start=2026-08-03）: ${withContext.completion.values.join(", ")}` +
    ` ／ context なし: ${withoutContext.completion.values.length} 件`,
);

const exported = (await client.callTool({
  name: "export_report",
  arguments: { from: "2026-07-27", to: "2026-08-07" },
})) as { structuredContent?: { uri?: string; newlyListed?: boolean } };
await sleep(100);
const afterExport = await client.listResources();
console.log(
  `[13/14] export_report: uri=${exported.structuredContent?.uri}` +
    ` / newlyListed=${exported.structuredContent?.newlyListed}` +
    ` / resources/list=${afterExport.resources.length} 件 / list_changed 通知=${listChangedCount} 件`,
);

// 購読 → データ更新 → 通知 → 購読解除 → データ更新（通知が来ないこと）
await client.subscribeResource({ uri: "dashboard://summary/current" });
const added = (await client.callTool({
  name: "add_work_log",
  arguments: { memberId: "m-003", projectId: "p-report", date: "2026-08-07", hours: 3 },
})) as { structuredContent?: { revision?: number } };
await sleep(100);
const countWhileSubscribed = updatedUris.length;

await client.unsubscribeResource({ uri: "dashboard://summary/current" });
const addedAgain = (await client.callTool({
  name: "add_work_log",
  arguments: { memberId: "m-001", projectId: "p-portal", date: "2026-08-07", hours: 2 },
})) as { structuredContent?: { revision?: number } };
await sleep(100);
console.log(
  `[14/14] 購読: updated 通知=${countWhileSubscribed} 件（${updatedUris.join(", ")}）` +
    ` / revision 1→${added.structuredContent?.revision}` +
    ` / 解除後の通知=${updatedUris.length - countWhileSubscribed} 件（revision=${addedAgain.structuredContent?.revision}）`,
);

// 異常系：購読できない URI・未知の用語・パーセントエンコードしたパストラバーサル
const codes: string[] = [];
for (const [label, action] of [
  ["購読できない URI", () => client.subscribeResource({ uri: "glossary://sprint" })],
  ["未知の用語", () => client.readResource({ uri: "glossary://unknown-term" })],
  [
    "パーセントエンコードした traversal",
    () => client.readResource({ uri: "glossary://..%2f..%2f..%2f..%2fetc%2fpasswd" }),
  ],
] as const) {
  try {
    await action();
    codes.push(`${label}=成功してしまった`);
  } catch (error) {
    codes.push(`${label}=${errorCodeOf(error)}`);
  }
}
console.log(`[補足] ${codes.join(" / ")}`);

await client.close();
console.log("OK: セッション6 のリソースとプロンプトは仕様どおりに応答しています");
