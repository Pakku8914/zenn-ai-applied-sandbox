/**
 * 問題7 の解答：readOnlyHint の申告と振る舞いが一致しているかを検査する
 *
 *   docker compose exec node npx tsx src/session05/answers/q7-audit.ts src/session05/server.ts
 *   docker compose exec node npx tsx src/session05/answers/q7-audit.ts src/session05/answers/q7-bad-server.ts
 *
 * 手順：状態のスナップショットを取る → 読み取り専用ツールを 1 本呼ぶ →
 * スナップショットを取り直して比較する。変化したら申告が嘘である。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

/** 状態を読み出すための呼び出し（観測手段）。存在するものだけ使う */
const PROBES: Array<{ name: string; arguments: Record<string, unknown> }> = [
  { name: "list_members", arguments: {} },
  { name: "list_projects", arguments: { includeArchived: true } },
];

/** 検査対象を呼ぶときに渡す既知の引数 */
const KNOWN_ARGS: Record<string, Record<string, unknown>> = {
  list_members: {},
  list_projects: { includeArchived: true },
  summarize_hours: { from: "2026-08-03", to: "2026-08-07" },
  export_report: { from: "2026-08-03", to: "2026-08-07" },
  exportReportCSV: { from: "2026-08-03", to: "2026-08-07" },
  archive_project: { projectId: "p-portal", reason: "注釈の検査" },
};

type ToolResult = { isError?: boolean; content: unknown; structuredContent?: unknown; [key: string]: unknown };

const entry = process.argv[2] ?? "src/session05/server.ts";
const transport = new StdioClientTransport({ command: "npx", args: ["tsx", entry] });
const client = new Client({ name: "annotation-audit", version: "1.0.0" });
await client.connect(transport);

const { tools } = await client.listTools();
const names = new Set(tools.map((tool) => tool.name));
const probes = PROBES.filter((probe) => names.has(probe.name));

async function snapshot(): Promise<string> {
  const parts: string[] = [];
  for (const probe of probes) {
    const result = (await client.callTool({
      name: probe.name,
      arguments: probe.arguments,
    })) as ToolResult;
    parts.push(JSON.stringify(result.structuredContent ?? result.content));
  }
  return parts.join("|");
}

const targets = tools
  .filter((tool) => tool.annotations?.readOnlyHint === true)
  .map((tool) => tool.name)
  .sort((a, b) => a.localeCompare(b));
console.log(`検査対象（readOnlyHint: true）: ${targets.join(", ")}`);

const changed: string[] = [];
const skipped: string[] = [];
let before = await snapshot();

for (const name of targets) {
  try {
    const result = (await client.callTool({
      name,
      arguments: KNOWN_ARGS[name] ?? {},
    })) as ToolResult;
    if (result.isError === true) {
      skipped.push(name);
      continue;
    }
  } catch {
    // JSON-RPC エラーでも「検証できなかった」に分類する（状態変化とは区別する）
    skipped.push(name);
    continue;
  }
  const after = await snapshot();
  if (after !== before) {
    changed.push(name);
    before = after;
  }
}

console.log(
  `検証できなかったツール（呼び出しが失敗）: ${skipped.length === 0 ? "なし" : skipped.join(", ")}`,
);
console.log(`状態が変化したツール: ${changed.length === 0 ? "なし" : changed.join(", ")}`);
console.log(
  changed.length === 0
    ? "判定: 合格（readOnlyHint の申告と振る舞いが一致しています）"
    : "判定: 不合格（readOnlyHint: true を申告したツールが状態を変えました）",
);

await client.close();
