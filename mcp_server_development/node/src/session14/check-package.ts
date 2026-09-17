/**
 * 配布物の中身を検査するスクリプト
 *
 *   docker compose exec node npx tsx src/session14/check-package.ts src/session14/docsearch-pkg
 *   docker compose exec node npx tsx src/session14/check-package.ts src/session14/leak-demo
 *
 * 検査するもの
 *   ① 配布物に入るファイル一覧（npm pack --json を実際に走らせて取得する）
 *   ② package.json の bin / exports / main が指すファイルが一覧に含まれているか
 *   ③ 配布してはいけないファイル名が混ざっていないか
 *   ④ 配布物の本文に秘密情報らしき文字列が無いか（最後の網）
 *
 * 終了コード 0 = 合格 / 1 = 不合格。CI にそのまま載せられます（セッション13）。
 * これはクライアント側の道具なので console.log を使ってかまいません。
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

type PackedFile = { readonly path: string; readonly size: number };
type PackResult = {
  readonly name: string;
  readonly version: string;
  readonly filename: string;
  readonly files: readonly PackedFile[];
};
type Manifest = {
  readonly bin?: string | Record<string, string>;
  readonly main?: string;
  readonly exports?: string | Record<string, unknown>;
  readonly private?: boolean;
};

/** 配布物に入っていたら不合格にするファイル名のパターン */
const FORBIDDEN_PATHS: ReadonlyArray<{ label: string; test: RegExp }> = [
  { label: "環境変数ファイル", test: /(^|\/)\.env(\..+)?$/ },
  { label: "秘密鍵・証明書", test: /\.(pem|key|p12|pfx)$/ },
  { label: "npm 認証情報", test: /(^|\/)\.npmrc$/ },
  { label: "SSH 鍵", test: /(^|\/)id_(rsa|ed25519)$/ },
  { label: "ログ", test: /\.log$/ },
  { label: "依存ディレクトリ", test: /(^|\/)node_modules\// },
  { label: "内部メモ", test: /(^|\/)(notes|internal|secrets)(\/|$)/ },
  { label: "過去の配布物", test: /\.tgz$/ },
];

/** 本文に現れたら不合格にするパターン。一致した値そのものは出力しない */
const SECRET_CONTENTS: ReadonlyArray<{ label: string; re: RegExp }> = [
  { label: "PEM 形式の秘密鍵", re: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  { label: "AWS アクセスキー ID", re: /AKIA[0-9A-Z]{16}/ },
  {
    label: "トークンらしき代入",
    re: /(token|secret|password|passwd|api[_-]?key)\s*[:=]\s*["']?[A-Za-z0-9_\-]{16,}/i,
  },
];

const MAX_SCAN_BYTES = 1024 * 1024;

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** npm pack を実際に走らせて、配布物の一覧と tarball を得る */
function pack(packageDir: string): PackResult {
  const raw = execFileSync("npm", ["pack", "--json"], {
    cwd: packageDir,
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  });
  // npm の版によって JSON の前後に別の行が混ざることがあるため、配列部分だけを切り出す
  const start = raw.indexOf("[");
  const end = raw.lastIndexOf("]");
  if (start < 0 || end < start) {
    throw new Error("npm pack --json の出力を解釈できませんでした");
  }
  const results = JSON.parse(raw.slice(start, end + 1)) as PackResult[];
  const first = results[0];
  if (first === undefined) {
    throw new Error("npm pack --json が空の結果を返しました");
  }
  return first;
}

/** bin / main / exports が指す先を集める（"./dist/x.js" と "dist/x.js" を同じ形に揃える） */
function entryTargets(manifest: Manifest): string[] {
  const targets: string[] = [];
  if (typeof manifest.bin === "string") {
    targets.push(manifest.bin);
  } else if (manifest.bin !== undefined) {
    targets.push(...Object.values(manifest.bin));
  }
  if (typeof manifest.main === "string") {
    targets.push(manifest.main);
  }
  if (typeof manifest.exports === "string") {
    targets.push(manifest.exports);
  } else if (manifest.exports !== undefined) {
    for (const value of Object.values(manifest.exports)) {
      if (typeof value === "string") {
        targets.push(value);
      }
    }
  }
  return targets.map((target) => target.replace(/^\.\//, ""));
}

/** tarball を一時ディレクトリに展開し、本文をスキャンする */
function scanContents(packageDir: string, filename: string): string[] {
  const findings: string[] = [];
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "pkgcheck-"));
  try {
    execFileSync("tar", ["-xzf", path.resolve(packageDir, filename), "-C", workDir]);
    const root = path.join(workDir, "package");
    const walk = (dir: string): void => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(full);
          continue;
        }
        if (fs.statSync(full).size > MAX_SCAN_BYTES) {
          continue; // 巨大ファイルは飛ばす（画像などを想定）
        }
        const text = fs.readFileSync(full, "utf8");
        for (const pattern of SECRET_CONTENTS) {
          if (pattern.re.test(text)) {
            // 一致した値は出さない。検査ツール自身が秘密を漏らしてはいけない
            findings.push(`${pattern.label}（${path.relative(root, full)}）`);
          }
        }
      }
    };
    walk(root);
  } finally {
    fs.rmSync(workDir, { recursive: true, force: true });
  }
  return findings;
}

const packageDir = process.argv[2];
if (packageDir === undefined) {
  console.error("使い方: npx tsx src/session14/check-package.ts <パッケージのディレクトリ>");
  process.exit(2);
}

const result = pack(packageDir);
const manifest = JSON.parse(
  fs.readFileSync(path.join(packageDir, "package.json"), "utf8"),
) as Manifest;
const files = result.files.map((file) => file.path).sort(compare);

console.log(`[check] 対象: ${packageDir}`);
console.log(`[check] パッケージ: ${result.name}@${result.version}`);
console.log(`[check] 作成した tarball: ${result.filename}（サイズは環境で変わります）`);
console.log(`[check] 配布ファイル数: ${files.length}`);
for (const file of files) {
  console.log(`        ${file}`);
}

const problems: string[] = [];
const warnings: string[] = [];

for (const file of files) {
  for (const pattern of FORBIDDEN_PATHS) {
    if (pattern.test.test(file)) {
      problems.push(`配布してはいけないファイルが含まれています: ${file}（${pattern.label}）`);
    }
  }
}

for (const target of entryTargets(manifest)) {
  if (!files.includes(target)) {
    problems.push(`package.json が指すファイルが配布物にありません: ${target}`);
  }
}

for (const finding of scanContents(packageDir, result.filename)) {
  problems.push(`本文に秘密情報らしき文字列が見つかりました: ${finding}`);
}

for (const expected of ["README.md", "LICENSE"]) {
  if (!files.includes(expected)) {
    warnings.push(`${expected} が配布物にありません（利用者が使い方とライセンスを知れません）`);
  }
}
if (manifest.private === true) {
  warnings.push("private: true が付いています（公開はできません。社内配布ならこれが正解です）");
}

for (const warning of warnings) {
  console.log(`WARN: ${warning}`);
}
if (problems.length > 0) {
  for (const problem of problems) {
    console.log(`NG: ${problem}`);
  }
  console.log(`NG: ${problems.length} 件の問題が見つかりました。公開してはいけません。`);
  process.exit(1);
}
console.log("OK: 配布物の中身に問題は見つかりませんでした");
