/**
 * セッション5 の確認用クライアント
 *
 *   docker compose exec node npx tsx src/session05/verify.ts
 *
 * このスクリプトはクライアント側なので console.log を使ってかまいません
 * （禁止されているのは「サーバープロセスの stdout」だけです）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

type ContentLike = {
  type: string;
  text?: string;
  uri?: string;
  name?: string;
  mimeType?: string;
  resource?: { uri: string; mimeType?: string; text?: string };
};

type ToolResult = {
  isError?: boolean;
  content: ContentLike[];
  structuredContent?: Record<string, unknown>; [key: string]: unknown };

/** SDK の戻り値を読みやすい形に寄せるだけのヘルパー（検証はサーバーと SDK が済ませている） */
function asResult(result: unknown): ToolResult {
  return result as ToolResult;
}

function field(result: ToolResult, key: string): unknown {
  return result.structuredContent?.[key];
}

/** 注釈を「ホストがどう解釈するか」に翻訳する。既定値の扱いが要点 */
function describeAnnotations(
  annotations:
    | {
        readOnlyHint?: boolean;
        destructiveHint?: boolean;
        idempotentHint?: boolean;
        openWorldHint?: boolean;
      }
    | undefined,
): string {
  if (annotations === undefined) {
    return "注釈なし";
  }
  const labels: string[] = [];
  const readOnly = annotations.readOnlyHint === true;
  if (readOnly) {
    labels.push("読み取り専用");
  } else {
    // destructiveHint の既定は true。書いていなければ破壊的とみなす
    if (annotations.destructiveHint !== false) {
      labels.push("破壊的");
    }
    if (annotations.idempotentHint === true) {
      labels.push("冪等");
    }
  }
  if (annotations.openWorldHint === false) {
    labels.push("閉じた世界");
  }
  return labels.join("+");
}

const transport = new StdioClientTransport({
  command: "npx",
  args: ["tsx", "src/session05/server.ts"],
});
const client = new Client({ name: "session05-verify", version: "1.0.0" });
await client.connect(transport);

const info = client.getServerVersion();
const { tools } = await client.listTools();
const sorted = [...tools].sort((a, b) => a.name.localeCompare(b.name));
console.log(
  `[1/10] 接続: ${info?.name} v${info?.version} / tools=${sorted.map((tool) => tool.name).join(", ")}`,
);

console.log(
  `[2/10] outputSchema を宣言しているツール: ${sorted
    .filter((tool) => tool.outputSchema !== undefined)
    .map((tool) => tool.name)
    .join(", ")}`,
);

console.log(
  `[3/10] 注釈: ${sorted
    .map((tool) => `${tool.name}=${describeAnnotations(tool.annotations)}`)
    .join(" / ")}`,
);

const week = asResult(
  await client.callTool({
    name: "summarize_hours",
    arguments: { from: "2026-08-03", to: "2026-08-07" },
  }),
);
console.log(
  `[4/10] summarize_hours: totalHours=${field(week, "totalHours")} / memberCount=${field(week, "memberCount")} / content[0].type=${week.content[0]?.type}`,
);

// outputSchema を宣言していても、isError のときは structuredContent を返さなくてよい
const tooLong = asResult(
  await client.callTool({
    name: "summarize_hours",
    arguments: { from: "2026-01-01", to: "2026-08-05" },
  }),
);
console.log(
  `[5/10] 期間超過: isError=${tooLong.isError === true} / structuredContent なし=${tooLong.structuredContent === undefined}`,
);

// 形式違反は Zod が弾き、JSON-RPC エラーになる（ツール実行層まで届かない）
// スキーマ違反は例外ではなく isError: true のツール結果として返ります
// （JSON-RPC エラーになるのは、そのメソッド自体を受け付けられないときだけ）
const badFormat = await client.callTool({
  name: "summarize_hours",
  arguments: { from: "2026/08/03", to: "2026-08-07" },
});
const badBlocks = (asResult(badFormat).content ?? []) as Array<{ text?: string }>;
const layer =
  asResult(badFormat).isError === true
    ? `ツール実行層 isError=true / ${(badBlocks[0]?.text ?? "").slice(0, 40)}`
    : "エラーになりませんでした（検証が効いていません）";
console.log(`[6/10] 形式違反（from=2026/08/03）: ${layer}`);

const first = asResult(
  await client.callTool({
    name: "archive_project",
    arguments: { projectId: "p-search", reason: "検索基盤の刷新完了に伴う終了" },
  }),
);
const second = asResult(
  await client.callTool({
    name: "archive_project",
    arguments: { projectId: "p-search", reason: "重複呼び出しの確認" },
  }),
);
const missing = asResult(
  await client.callTool({
    name: "archive_project",
    arguments: { projectId: "p-unknown", reason: "存在しない ID の確認" },
  }),
);
console.log(
  `[7/10] archive_project: 1回目 alreadyArchived=${field(first, "alreadyArchived")} / 2回目=${field(second, "alreadyArchived")} / affectedWorkLogs=${field(first, "affectedWorkLogs")}`,
);
console.log(
  `[8/10] 冪等性の確認: 残りのアクティブ=${(field(first, "remainingActiveProjects") as string[]).join(",")} / 未知の ID は isError=${missing.isError === true}`,
);

const linked = asResult(
  await client.callTool({
    name: "export_report",
    arguments: { from: "2026-07-27", to: "2026-08-07" },
  }),
);
const inlined = asResult(
  await client.callTool({
    name: "export_report",
    arguments: { from: "2026-07-27", to: "2026-08-07", inline: true },
  }),
);
const link = linked.content.find((block) => block.type === "resource_link");
const embedded = inlined.content.find((block) => block.type === "resource");
console.log(
  `[9/10] export_report: rows=${field(linked, "rows")} / byteSize=${field(linked, "byteSize")} / 種別=${linked.content
    .map((block) => block.type)
    .join(",")} / uri=${link?.uri} / mimeType=${link?.mimeType}`,
);
console.log(
  `[10/10] 埋め込み版: 種別=${inlined.content.map((block) => block.type).join(",")} / 本文の先頭=${embedded?.resource?.text?.split("\n")[0]} / レスポンスは参照版より大きい=${JSON.stringify(inlined).length > JSON.stringify(linked).length}`,
);

// resource_link の URI は resources/read で読める必要がある（次章で実装します）
let readState = "読み取れました（想定外）";
try {
  await client.readResource({ uri: link?.uri ?? "" });
} catch {
  readState = "このサーバーは resources 未対応です（セッション6 で実装します）";
}
console.log(`[補足] ${link?.uri} の読み取り: ${readState}`);

await client.close();
console.log("OK: セッション5 のツールは仕様どおりに応答しています");
