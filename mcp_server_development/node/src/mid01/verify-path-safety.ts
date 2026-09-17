/**
 * パス検証の異常系をまとめて確認するスクリプト（ドメイン層だけを使う）
 *
 *   docker compose exec node npx tsx src/mid01/verify-path-safety.ts
 *   docker compose exec node npx tsx src/mid01/verify-path-safety.ts /tmp/mid01-docs
 *
 * MCP を通さないので、URI の正規化（WHATWG URL）に影響されず「検証ロジックそのもの」を
 * 確認できます。resources/read 経由では URL 正規化で .. の一部が消えることがあり、
 * 「どの理由で落ちたか」がずれる場合があります ―― だからドメイン層で確認します。
 *
 * クライアント側のスクリプトなので console.log を使ってかまいません。
 */
import { resolveDocsRoot } from "./config.js";
import { createDocRepository } from "./domain/doc-repository.js";
import { type RejectReason, resolveSafeDocPath } from "./domain/safe-path.js";

/** 前章 S1 の受け入れ条件（構文レベルで落ちるもの） */
const SYNTAX_CASES: readonly (readonly [input: string, expected: RejectReason])[] = [
  ["../../etc/passwd", "parent_traversal"],
  ["/etc/passwd", "absolute_path"],
  ["..%2f..%2fetc%2fpasswd", "parent_traversal"],
  ["%2e%2e%2fsecret.md", "parent_traversal"],
  ["guides/../../etc/passwd", "parent_traversal"],
  ["C:\\windows\\win.ini", "drive_letter"],
  ["guides\\vpn-setup.md", "backslash"],
  ["onboarding.md%00.txt", "control_character"],
  ["onboarding.txt", "not_markdown"],
  ["guides", "not_markdown"],
  ["a/b/c/d/e.md", "too_deep"],
];

/** シンボリックリンクを仕込んだディレクトリでのみ有効なケース */
const SYMLINK_CASES: readonly (readonly [input: string, expected: RejectReason])[] = [
  ["leaked.md", "symlink"],
  ["external/leak.md", "symlink"],
];

const docsRoot = resolveDocsRoot();
const repository = createDocRepository(docsRoot);
let failures = 0;

function report(input: string, expected: RejectReason): void {
  const result = resolveSafeDocPath(docsRoot, input);
  const actual = result.ok ? "許可されてしまった" : result.reason;
  const verdict = actual === expected ? "OK" : "NG";
  if (verdict === "NG") {
    failures += 1;
  }
  console.log(`  ${verdict}  ${input.padEnd(24)} → ${actual}（期待 ${expected}）`);
}

console.log(`docsRoot=${docsRoot}`);

const documents = repository.listDocuments();
console.log(
  `[1/4] listDocuments: ${documents.length} 件` +
    ` → ${documents.map((meta) => meta.relativePath).join(", ")}`,
);

console.log("[2/4] 危険な入力の判定");
for (const [input, expected] of SYNTAX_CASES) {
  report(input, expected);
}

console.log("[3/4] シンボリックリンクの判定");
for (const [input, expected] of SYMLINK_CASES) {
  const probe = resolveSafeDocPath(docsRoot, input);
  if (!probe.ok && probe.reason === "not_found") {
    // リンクを仕込んでいないディレクトリではスキップする
    console.log(`  --  ${input.padEnd(24)} → リンク未作成のためスキップ`);
    continue;
  }
  report(input, expected);
}

const good = resolveSafeDocPath(docsRoot, "guides/vpn-setup.md");
console.log(
  `[4/4] 正常な入力: ok=${good.ok} / relativePath=${good.ok ? good.relativePath : "-"}`,
);

if (failures === 0) {
  console.log("OK: すべての入力が期待どおりに判定されました");
} else {
  console.log(`NG: ${failures} 件が期待と異なります`);
  process.exitCode = 1;
}
