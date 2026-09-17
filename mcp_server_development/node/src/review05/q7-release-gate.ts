/**
 * リリースゲート（問題7）
 *
 *   docker compose exec node npx tsx src/review05/q7-release-gate.ts
 *   docker compose exec node npx tsx src/review05/q7-release-gate.ts --unsafe
 *   docker compose exec node npx tsx src/review05/q7-release-gate.ts --dump
 *
 * 終了コード 0 = 全項目合格 / 1 = 1 件でも失敗。
 * ネットワークにも実時間にも依存しません（インメモリ接続と文字列検査だけ）。
 *
 * ★ 検査項目の番号は固定です。項目を足すときは末尾に足してください
 *   （途中に挿入すると、過去の CI ログと突き合わせられなくなります）。
 */
import {
  createGateServer,
  SERVER_NAME,
  SERVER_VERSION,
  type Scope,
} from "./gate-server.js";
import { callTool, connectInMemory, digestTools, type ToolDigest } from "./harness.js";
import { reviewToolResult } from "./q5-output-review.js";

const unsafe = process.argv.includes("--unsafe");
const dump = process.argv.includes("--dump");
const NONCE = "deadbeefdeadbeef";
const ALL_SCOPES: readonly Scope[] = ["requests:read", "requests:approve"];

/**
 * 07 のベースライン。引数を 1 つ改名するとここと食い違って赤くなります。
 * 意図した変更なら --dump の出力で更新し、その差分をレビューに載せてください。
 */
const BASELINE: ToolDigest[] = [
  {
    name: "decide_request",
    title: "申請の承認・却下",
    annotations: {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false,
    },
    args: [
      { name: "confirm", required: false, hasDescription: true },
      { name: "decision", required: true, hasDescription: true },
      { name: "id", required: true, hasDescription: true },
    ],
    hasOutputSchema: true,
  },
  {
    name: "get_request",
    title: "申請の詳細取得",
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    args: [{ name: "id", required: true, hasDescription: true }],
    hasOutputSchema: false,
  },
  {
    name: "search_requests",
    title: "申請の検索",
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    args: [
      { name: "limit", required: false, hasDescription: true },
      { name: "query", required: false, hasDescription: true },
      { name: "status", required: false, hasDescription: true },
    ],
    hasOutputSchema: true,
  },
];

/** outputSchema を宣言したツールを「成功する引数」で呼ぶための対応表 */
const SUCCESS_CALLS: Record<string, Record<string, unknown>> = {
  // decide_request は confirm を付けない（ドライラン）。ゲートが状態を変えてはいけない
  decide_request: { id: "req-1001", decision: "approve" },
  search_requests: { query: "購入" },
};

const results: { id: string; label: string; ok: boolean; detail: string }[] = [];
function check(id: string, label: string, ok: boolean, detail = ""): void {
  results.push({ id, label, ok, detail });
}

const auditLines: string[] = [];
const client = await connectInMemory(
  createGateServer({
    scopes: ALL_SCOPES,
    sanitize: !unsafe,
    nonce: () => NONCE,
    audit: (line) => auditLines.push(line),
  }),
  "release-gate",
);
const { tools } = await client.listTools();
const digests = digestTools(tools);

if (dump) {
  console.log(JSON.stringify(digests, null, 2));
  await client.close();
  process.exit(0);
}

// 01 ―― ツール定義自体がコンテキストを消費する（セッション10）
check("01", "ツール数が 6 本以内である", tools.length <= 6, `${tools.length} 本`);

// 02
const untitled = digests.filter((tool) => tool.title === null).map((tool) => tool.name);
check("02", "すべてのツールに title がある", untitled.length === 0, untitled.join(", "));

// 03 ―― 4 つのうち 1 つでも省略すると、ホストは「不明」として扱う
const missingAnnotations = digests
  .filter((tool) => Object.values(tool.annotations).some((value) => value === null))
  .map((tool) => tool.name);
check(
  "03",
  "すべてのツールに 4 つの注釈が明示されている",
  missingAnnotations.length === 0,
  missingAnnotations.join(", "),
);

// 04 ―― 破壊的操作は二段階（セッション10）
const destructive = digests.filter((tool) => tool.annotations.destructiveHint === true);
const withoutDryRun = destructive
  .filter((tool) => !tool.args.some((arg) => arg.name === "confirm" && !arg.required))
  .map((tool) => tool.name);
check(
  "04",
  "破壊的ツールにドライラン用の引数がある",
  withoutDryRun.length === 0,
  withoutDryRun.length === 0 ? `対象 ${destructive.length} 本` : `不足: ${withoutDryRun.join(", ")}`,
);

// 05
const missingDescription = digests.flatMap((tool) =>
  tool.args.filter((arg) => !arg.hasDescription).map((arg) => `${tool.name}.${arg.name}`),
);
check(
  "05",
  "すべての引数に description がある",
  missingDescription.length === 0,
  missingDescription.join(", "),
);

// 06 ―― 「宣言しているのに返していない」を捕まえる
const declared = digests.filter((tool) => tool.hasOutputSchema).map((tool) => tool.name);
const withoutStructured: string[] = [];
for (const name of declared) {
  const args = SUCCESS_CALLS[name];
  if (args === undefined) {
    withoutStructured.push(`${name}（成功する呼び出しが未定義）`);
    continue;
  }
  const result = await callTool(client, name, args);
  if (result.isError === true || result.structuredContent === undefined) {
    withoutStructured.push(name);
  }
}
check(
  "06",
  "outputSchema を宣言したツールは structuredContent を返す",
  withoutStructured.length === 0,
  withoutStructured.length === 0 ? `対象 ${declared.length} 本` : withoutStructured.join(", "),
);

// 07 ―― キーの並び順まで含めて比較する（digestTools が返す順序でベースラインを書く）
const digestMatches = JSON.stringify(digests) === JSON.stringify(BASELINE);
check(
  "07",
  "スキーマダイジェストがベースラインと一致する",
  digestMatches,
  digestMatches ? "" : "差分あり。意図した変更なら --dump で更新し、差分をレビューに載せること",
);

// 08 ―― 権限最小化が「実装の事実」かどうか
const limitedClient = await connectInMemory(
  createGateServer({
    scopes: ["requests:read"],
    sanitize: !unsafe,
    nonce: () => NONCE,
    audit: () => {},
  }),
  "release-gate-limited",
);
const denied = await callTool(limitedClient, "decide_request", {
  id: "req-1001",
  decision: "approve",
});
const deniedText = denied.content.map((block) => block.text ?? "").join("\n");
await limitedClient.close();
const scopeEnforced = denied.isError === true && deniedText.includes("requests:approve");
check(
  "08",
  "権限の無いスコープでは破壊的ツールが拒否される",
  scopeEnforced,
  scopeEnforced ? "" : "拒否されなかった、または拒否理由に必要なスコープ名が無い",
);

// 09 ―― 外部データを含む応答をレビューする
const problems09: string[] = [];
for (const id of ["req-1004", "req-1006"]) {
  const review = reviewToolResult(JSON.stringify(await callTool(client, "get_request", { id })));
  if (!review.ok) problems09.push(`${id}: ${review.problems.join(" / ")}`);
}
check("09", "応答に指示文・秘密情報が残っていない", problems09.length === 0, problems09.join(" | "));

// 10 ―― 監査ログに生値が出ていないこと。渡していない値は消しようがない
const RAW_VALUES = ["購入", "req-1001", "req-1004", "req-1006", "ghp_R05ExampleTokenAbcd1234"];
const joined = auditLines.join("\n");
const leaked = RAW_VALUES.filter((value) => joined.includes(value));
check(
  "10",
  "監査ログに引数の生値と秘密情報が含まれていない",
  auditLines.length > 0 && leaked.length === 0,
  auditLines.length === 0 ? "監査ログが 1 行も出ていない" : leaked.join(", "),
);

await client.close();

console.log(`[gate] 対象: ${SERVER_NAME}@${SERVER_VERSION}${unsafe ? "（--unsafe: サニタイズ無効）" : ""}`);
let failed = 0;
for (const row of results) {
  if (!row.ok) failed += 1;
  const detail = row.detail === "" ? "" : `（${row.detail}）`;
  console.log(`${row.ok ? "PASS" : "FAIL"} ${row.id} ${row.label}${detail}`);
}
console.log(`[gate] ${results.length} 件中 ${results.length - failed} 件が合格`);
if (failed > 0) {
  console.log(`NG: ${failed} 件の検査に失敗しました。リリースしてはいけません。`);
  process.exitCode = 1;
} else {
  console.log("OK: リリースゲートを通過しました");
}
