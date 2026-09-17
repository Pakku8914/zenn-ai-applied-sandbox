/**
 * プロンプトインジェクションの実験（攻撃前 / 緩和後を 1 本で比較する）
 *
 * 実行:
 *   docker compose exec node npx tsx src/session15/verify-injection.ts
 *   docker compose exec node npx tsx src/session15/verify-injection.ts src/session15/docs-tainted
 *
 * 攻撃前  : 中間プロジェクト1 のサーバー（createDocSearchServer）
 * 緩和後  : 本章のサーバー（createGuardedDocSearchServer）
 * 判定    : サーバーの応答（JSON 文字列）に指示文パターンが含まれるかを機械的に見る
 *
 * このスクリプトはクライアント側なので console.log を使ってかまいません。
 * 禁止されているのは「サーバープロセスの stdout」だけです。
 */
import path from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { createDocSearchServer } from "../mid01/create-server.js";
import { createAuditLogger } from "./audit-log.js";
import { createGuardedDocSearchServer } from "./guarded-server.js";
import { createRateLimiter } from "./rate-limit.js";
import { createUntrustedBoundary, detectDirectives, inspectOutput } from "./sanitize.js";

/** 検証では nonce を固定する（毎回同じ出力にするため。本番は必ずランダム） */
const FIXED_NONCE = "verify0000000000";
/** 時計も固定する。durationMs が 0 になり、出力が完全に決定的になる */
const FIXED_TIME = 1_700_000_000_000;
const QUERY = "VPN";

const docsRoot = path.resolve(process.argv[2] ?? "src/session15/docs-tainted");
const boundary = createUntrustedBoundary(FIXED_NONCE);
const failures: string[] = [];

function check(label: string, actual: unknown, expected: unknown): void {
  if (actual !== expected) {
    failures.push(`${label}（期待=${String(expected)} / 実際=${String(actual)}）`);
  }
}

async function connect(server: McpServer): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "session15-verify", version: "1.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return client;
}

type Structured = {
  totalMatched?: number;
  results?: { path: string; score: number }[];
};

/** 応答に含まれる指示文を数える。判定はこれ 1 本 */
function probe(payload: unknown): { count: number; ids: string } {
  const findings = detectDirectives(JSON.stringify(payload));
  const ids = [...new Set(findings.map((finding) => finding.id))].sort().join(",");
  return { count: findings.length, ids: ids === "" ? "なし" : ids };
}

function head(payload: unknown): string {
  const structured = (payload as { structuredContent?: Structured }).structuredContent;
  const first = structured?.results?.[0];
  return first === undefined ? "なし" : `${first.path}（score=${first.score}）`;
}

console.log(`[準備] 汚染ディレクトリ=${docsRoot} / 検索語="${QUERY}"`);

// ------------------------------------------------------------------
// 攻撃前 ―― 中間プロジェクト1 のサーバーをそのまま使う
// ------------------------------------------------------------------
const before = await connect(createDocSearchServer({ docsRoot }));

const beforeTool = await before.callTool({
  name: "search_documents",
  arguments: { query: QUERY },
});
const beforeToolProbe = probe(beforeTool);
const beforeInspect = inspectOutput(JSON.stringify(beforeTool), boundary);
console.log(
  `[1/10] [攻撃前] search_documents: 一致 ` +
    `${(beforeTool as { structuredContent?: Structured }).structuredContent?.totalMatched} 件` +
    ` / 1件目=${head(beforeTool)}`,
);
console.log(
  `[2/10] [攻撃前] 指示文が出力に含まれる: ${beforeToolProbe.count > 0}` +
    `（検出=${beforeToolProbe.ids} / ${beforeToolProbe.count} 箇所）`,
);
console.log(
  `[3/10] [攻撃前] 外部データが境界で囲まれている: ${beforeInspect.untrustedBlocks > 0}` +
    `（境界ブロック ${beforeInspect.untrustedBlocks} 個）`,
);

const beforePrompt = await before.getPrompt({
  name: "summarize_search",
  arguments: { query: QUERY },
});
const beforePromptProbe = probe(beforePrompt);
console.log(
  `[4/10] [攻撃前] summarize_search: 指示文が出力に含まれる: ${beforePromptProbe.count > 0}` +
    `（${beforePromptProbe.count} 箇所 / メッセージ ${beforePrompt.messages.length} 件）`,
);
await before.close();

// ------------------------------------------------------------------
// 緩和後 ―― 本章のガード付きサーバー
// ------------------------------------------------------------------
const logLines: string[] = [];
const audit = createAuditLogger({
  server: "docsearch-guarded",
  tenantId: "acme",
  subjectId: "user-42",
  sessionId: "session-1",
  pepper: "verify-only-pepper-do-not-use-in-production",
  clock: () => FIXED_TIME,
  // 検証では配列に集める。既定の出力先は stderr（stdout は JSON-RPC の通信路）
  sink: (line) => logLines.push(line),
});
const limiter = createRateLimiter({
  capacity: 100,
  refillPerSecond: 10,
  now: () => FIXED_TIME,
});

const after = await connect(
  createGuardedDocSearchServer({
    docsRoot,
    tenant: { tenantId: "acme", subjectId: "user-42", sessionId: "session-1" },
    audit,
    limiter,
    nonce: () => FIXED_NONCE,
    clock: () => FIXED_TIME,
  }),
);

const afterTool = await after.callTool({
  name: "search_documents",
  arguments: { query: QUERY },
});
const afterToolProbe = probe(afterTool);
const afterInspect = inspectOutput(JSON.stringify(afterTool), boundary);
console.log(
  `[5/10] [緩和後] search_documents: 一致 ` +
    `${(afterTool as { structuredContent?: Structured }).structuredContent?.totalMatched} 件` +
    ` / 1件目=${head(afterTool)}`,
);
console.log(
  `[6/10] [緩和後] 指示文が出力に含まれる: ${afterToolProbe.count > 0}` +
    `（検出=${afterToolProbe.ids} / ${afterToolProbe.count} 箇所）`,
);
console.log(
  `[7/10] [緩和後] 外部データが境界で囲まれている: ${afterInspect.untrustedBlocks > 0}` +
    `（境界ブロック ${afterInspect.untrustedBlocks} 個 / nonce=${FIXED_NONCE}）`,
);
console.log(
  `[8/10] [緩和後] 境界の内側に残った命令形: ${afterInspect.imperativesInUntrusted} 件` +
    "（サニタイズでは消えない。境界と権限最小化で受け止める）",
);

const afterPrompt = await after.getPrompt({
  name: "summarize_search",
  arguments: { query: QUERY },
});
const afterPromptProbe = probe(afterPrompt);
const afterPromptInspect = inspectOutput(JSON.stringify(afterPrompt), boundary);
console.log(
  `[9/10] [緩和後] summarize_search: 指示文が出力に含まれる: ${afterPromptProbe.count > 0}` +
    ` / 境界ブロック ${afterPromptInspect.untrustedBlocks} 個` +
    ` / メッセージ ${afterPrompt.messages.length} 件`,
);

const rawQueryInLog = logLines.filter((line) => line.includes(QUERY)).length;
const fields = Object.keys(JSON.parse(logLines[0] ?? "{}") as Record<string, unknown>).join(",");
console.log(
  `[10/10] 監査ログ ${logLines.length} 行 / 生クエリの出現 ${rawQueryInLog} 件 / フィールド=${fields}`,
);
await after.close();

// ------------------------------------------------------------------
// 判定
// ------------------------------------------------------------------
check("攻撃前・ツール結果に指示文が含まれる", beforeToolProbe.count > 0, true);
check("攻撃前・プロンプトに指示文が含まれる", beforePromptProbe.count > 0, true);
check("攻撃前・境界が無い", beforeInspect.untrustedBlocks, 0);
check("緩和後・ツール結果に指示文が含まれない", afterToolProbe.count > 0, false);
check("緩和後・プロンプトに指示文が含まれない", afterPromptProbe.count > 0, false);
check("緩和後・境界ブロックがある", afterInspect.untrustedBlocks > 0, true);
check("緩和後・検索結果の件数と順序が変わらない", head(afterTool), head(beforeTool));
check("監査ログに生クエリが出ない", rawQueryInLog, 0);

if (failures.length === 0) {
  console.log("判定: OK（攻撃前 true → 緩和後 false / 検索結果は変わらない）");
} else {
  console.error(`判定: NG ―― ${failures.join(" / ")}`);
  process.exitCode = 1;
}
