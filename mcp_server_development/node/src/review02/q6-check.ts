/**
 * 検証なし（Bad）と検証あり（Good）を同じ入力で比べる。
 *
 *   docker compose exec node npx tsx src/review02/q6-setup.ts   # 先に置き場を作る
 *   docker compose exec node npx tsx src/review02/q6-check.ts
 *
 * MCP の層を通さずに関数を直接叩いているのは、出力を完全に決定的にするためです
 * （SDK の URI 照合の挙動に結果が左右されません）。
 * これは手元のスクリプトなので console.log を使ってかまいません。
 */
import { badResolveNoticeFile } from "./q6-fixture.js";
import { resolveNoticeFile } from "./q6-resolve.js";

const CASES = [
  { label: "正常な読み取り", raw: "fire-drill.md" },
  { label: "相対パスで外へ出る", raw: "..%2f..%2f..%2fetc%2fpasswd" },
  { label: "絶対パスを渡す", raw: "%2fetc%2fpasswd" },
  { label: "二重エンコード", raw: "%252e%252e%252f%252e%252e%252f%252e%252e%252fetc%252fpasswd" },
  { label: "シンボリックリンク", raw: "staff-only.md" },
  { label: "大文字", raw: "FIRE-DRILL.MD" },
] as const;

function errorNameOf(error: unknown): string {
  return (error as { code?: string }).code ?? "エラー";
}

console.log("== 検証なし（badResolveNoticeFile）==");
let reached = 0;
for (const [index, testCase] of CASES.entries()) {
  try {
    const { filePath, text } = await badResolveNoticeFile(testCase.raw);
    reached += 1;
    // 先頭 12 文字だけを出す（読めてしまったことの証拠として十分）
    console.log(
      `[${index + 1}] ${testCase.label}: 到達 ${filePath} 先頭12文字=${text.slice(0, 12)}`,
    );
  } catch (error) {
    console.log(
      `[${index + 1}] ${testCase.label}: 失敗 ${errorNameOf(error)}（読めなかっただけで、検証が効いたわけではありません）`,
    );
  }
}

console.log("== 検証あり（resolveNoticeFile）==");
let allowed = 0;
for (const [index, testCase] of CASES.entries()) {
  const result = await resolveNoticeFile(testCase.raw);
  if (result.ok) {
    allowed += 1;
    console.log(`[${index + 1}] ${testCase.label}: 許可 ${result.realPath}`);
  } else {
    console.log(`[${index + 1}] ${testCase.label}: 拒否 ${result.reason}`);
  }
}

console.log(
  `判定: Bad=${reached}/${CASES.length} が読めてしまう` +
    ` / Good=${allowed}/${CASES.length} だけ許可（正常な 1 件のみ）`,
);
