/**
 * Inspector CLI を使った E2E チェック（問題7-a の解答）
 *
 *   docker compose exec node npx tsx src/session13/e2e-inspector.ts
 *
 * 契約テストはインメモリなので速い代わりに、
 *   ・子プロセスとして起動できるか
 *   ・stdout を汚していないか
 *   ・依存が実行時にそろっているか
 * を検証していません。ここは公式ツールに叩かせます
 * （自作クライアントには自分の思い込みが入りますが、Inspector には入りません）。
 *
 * クライアント側のスクリプトなので stdout に書いてかまいません。
 * 失敗したら終了コードを 0 以外にすること（CI は終了コードしか見ません）。
 */
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);

const SERVER_ENTRY = "src/mid01/server.ts";
const EXPECTED_TOOL = "search_documents";
const EXPECTED_REQUIRED = ["query"];

const failures: string[] = [];

function check(label: string, ok: boolean, detail: string): void {
  if (ok) {
    console.log(`[e2e] OK  ${label}: ${detail}`);
    return;
  }
  console.error(`[e2e] NG  ${label}: ${detail}`);
  failures.push(label);
}

async function inspect(method: string): Promise<Record<string, unknown>> {
  const { stdout } = await run(
    "npx",
    ["mcp-inspector", "--cli", "npx", "tsx", SERVER_ENTRY, "--method", method],
    { timeout: 180_000, maxBuffer: 16 * 1024 * 1024 },
  );
  // サーバーが stderr に出したログが混ざって見えることがあるので、最初の { から読む
  const start = stdout.indexOf("{");
  if (start < 0) {
    throw new Error(`JSON が見つかりません: ${stdout.slice(0, 200)}`);
  }
  return JSON.parse(stdout.slice(start)) as Record<string, unknown>;
}

const listed = await inspect("tools/list");
const tools: unknown[] = Array.isArray(listed["tools"]) ? (listed["tools"] as unknown[]) : [];
const tool = tools.find(
  (entry): entry is Record<string, unknown> =>
    typeof entry === "object" &&
    entry !== null &&
    (entry as Record<string, unknown>)["name"] === EXPECTED_TOOL,
);

check("ツールが公開されている", tool !== undefined, EXPECTED_TOOL);

if (tool !== undefined) {
  const inputSchema = (tool["inputSchema"] ?? {}) as Record<string, unknown>;
  const required = Array.isArray(inputSchema["required"]) ? (inputSchema["required"] as unknown[]) : [];
  check(
    "必須引数",
    JSON.stringify(required) === JSON.stringify(EXPECTED_REQUIRED),
    JSON.stringify(required),
  );

  const annotations = (tool["annotations"] ?? {}) as Record<string, unknown>;
  check("読み取り専用の注釈", annotations["readOnlyHint"] === true, String(annotations["readOnlyHint"]));
}

if (failures.length > 0) {
  console.error(`NG: ${failures.length} 件の検査に失敗しました（${failures.join(" / ")}）`);
  process.exitCode = 1;
} else {
  console.log("OK: Inspector CLI 経由でも契約どおりに応答しました");
}
