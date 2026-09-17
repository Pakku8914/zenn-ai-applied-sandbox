/**
 * キャプチャログ（captures/stdio.log）を Markdown の要約表に整形する
 *
 * 種別の判定は id / method / result / error の 4 キーの有無だけで行います。
 * メソッド名の意味を使わないので、未知のメソッドが増えても直す必要がありません。
 *
 * 実行： docker compose exec node npx tsx src/session02/exercises/capture-summary.ts
 *
 * これはクライアント側（ログを読むだけ）のスクリプトなので console.log を使ってよい
 */
import { existsSync, readFileSync } from "node:fs";

const LOG_PATH = "captures/stdio.log";

if (!existsSync(LOG_PATH)) {
  console.log(`${LOG_PATH} が見つかりません。先にキャプチャを取ってください:`);
  console.log("  docker compose exec node npx tsx src/session02/capture.ts");
  process.exit(0);
}

type Kind = "リクエスト" | "レスポンス" | "エラー" | "通知";

interface Entry {
  index: number;
  direction: string;
  kind: Kind;
  id: string;
  method: string;
  summary: string;
}

/** 4 キーの有無だけで種別を決める。判定の順序が重要（error → result → id） */
function classify(message: Record<string, unknown>): Kind {
  if (message["error"] !== undefined) return "エラー";
  if (message["result"] !== undefined) return "レスポンス";
  if (message["id"] !== undefined) return "リクエスト";
  return "通知";
}

/** params / result / error のいずれかを 40 文字以内に要約する */
function summarize(message: Record<string, unknown>): string {
  const target = message["params"] ?? message["result"] ?? message["error"];
  if (target === undefined) return "-";
  // 表が崩れないようにパイプ記号をエスケープする
  const text = JSON.stringify(target).replaceAll("|", "\\|");
  return text.length <= 40 ? text : `${text.slice(0, 39)}…`;
}

const lines = readFileSync(LOG_PATH, "utf8")
  .split("\n")
  .filter((line) => line.length > 0);

const entries: Entry[] = lines.map((line, index) => {
  // 方向タグは 4 文字 + 半角スペース 1 文字。添字アクセスを避けて文字列操作で切り出す
  const direction = line.slice(0, 4);
  const message = JSON.parse(line.slice(5)) as Record<string, unknown>;
  const rawId = message["id"];
  const rawMethod = message["method"];
  return {
    index: index + 1,
    direction,
    kind: classify(message),
    id: rawId === undefined ? "-" : String(rawId),
    method: typeof rawMethod === "string" ? rawMethod : "-",
    summary: summarize(message),
  };
});

console.log("| # | 方向 | 種別 | id | method | 概要 |");
console.log("| -: | :--- | :--- | :- | :----- | :--- |");
for (const entry of entries) {
  console.log(
    `| ${entry.index} | ${entry.direction} | ${entry.kind} | ${entry.id} | ${entry.method} | ${entry.summary} |`,
  );
}

const requests = entries.filter((entry) => entry.kind === "リクエスト");
const errors = entries.filter((entry) => entry.kind === "エラー");
const responses = entries.filter(
  (entry) => entry.kind === "レスポンス" || entry.kind === "エラー",
);
const notifications = entries.filter((entry) => entry.kind === "通知");

// リクエストの id 集合からレスポンスの id 集合を引けば「未応答」が求まる
const answered = new Set(responses.map((entry) => entry.id));
const unanswered = requests
  .map((entry) => entry.id)
  .filter((id) => !answered.has(id));

console.log("");
console.log(
  `リクエスト ${requests.length} 件 / レスポンス ${responses.length} 件（エラー ${errors.length} 件）`,
);
console.log(
  `応答が返っていない id: ${unanswered.length === 0 ? "なし" : unanswered.join(", ")}`,
);
console.log(`通知 ${notifications.length} 件`);
