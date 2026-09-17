/**
 * 配布物の検査（問題3(b)）
 *
 *   docker compose exec node npx tsx src/review05/q3-check-dist.ts src/review05/release-candidate
 *
 * 検査するもの
 *   ① files から配布対象ファイルの一覧を組み立てる（package.json は常に含む）
 *   ② 配布してはいけないファイル名が混ざっていないか
 *   ③ bin / main / exports が指す先が配布対象に含まれているか
 *   ④ 配布対象の本文に秘密情報らしき文字列が無いか
 *
 * 終了コード 0 = 合格 / 1 = 不合格 / 2 = 使い方エラー。CI にそのまま載せられます。
 * クライアント側の道具なので console.log を使ってかまいません。
 */
import fs from "node:fs";
import path from "node:path";

type Manifest = {
  readonly name?: string;
  readonly version?: string;
  readonly files?: readonly string[];
  readonly bin?: string | Record<string, string>;
  readonly main?: string;
  readonly exports?: string | Record<string, unknown>;
};

/**
 * npm が常に配布物から除外する名前（本書で扱う分）。
 * files で許可しても入りません。ただし「入らないから安全」ではありません（(d) で扱います）。
 */
const ALWAYS_EXCLUDED: ReadonlySet<string> = new Set([".npmrc", "node_modules", ".git", ".DS_Store"]);

/** 配布物に入っていたら不合格にするファイル名 */
const FORBIDDEN_PATHS: ReadonlyArray<{ readonly label: string; readonly re: RegExp }> = [
  { label: "環境変数ファイル", re: /(^|\/)\.env(\..+)?$/ },
  { label: "秘密鍵・証明書", re: /\.(pem|key|p12|pfx)$/ },
  { label: "SSH 鍵", re: /(^|\/)id_(rsa|ed25519)$/ },
  { label: "ログ", re: /\.log$/ },
  { label: "内部メモ", re: /(^|\/)(notes|internal|secrets)(\/|$)/ },
  { label: "過去の配布物", re: /\.tgz$/ },
];

/**
 * 本文に現れたら不合格にするパターン。
 * g フラグを付けていないのは、test() で lastIndex を進めないためです。
 */
const SECRET_CONTENTS: ReadonlyArray<{ readonly label: string; readonly re: RegExp }> = [
  { label: "PEM 形式の秘密鍵", re: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  { label: "AWS アクセスキー ID", re: /AKIA[0-9A-Z]{16}/ },
  {
    label: "トークンらしき代入",
    re: /(token|secret|password|passwd|api[_-]?key)\s*[:=]\s*["']?[A-Za-z0-9_-]{16,}/i,
  },
];

const MAX_SCAN_BYTES = 1024 * 1024;

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function collect(dir: string, base: string, included: string[], excluded: string[]): void {
  const entries = fs
    .readdirSync(dir, { withFileTypes: true })
    .sort((a, b) => compare(a.name, b.name));
  for (const entry of entries) {
    const rel = base === "" ? entry.name : `${base}/${entry.name}`;
    if (ALWAYS_EXCLUDED.has(entry.name)) {
      excluded.push(rel);
      continue;
    }
    if (entry.isDirectory()) {
      collect(path.join(dir, entry.name), rel, included, excluded);
    } else {
      included.push(rel);
    }
  }
}

function buildFileList(
  packageDir: string,
  manifest: Manifest,
): { included: string[]; excluded: string[] } {
  // package.json は files に書かなくても必ず配布される
  const included: string[] = ["package.json"];
  const excluded: string[] = [];
  for (const entry of manifest.files ?? []) {
    const full = path.join(packageDir, entry);
    if (!fs.existsSync(full)) continue;
    if (fs.statSync(full).isDirectory()) {
      collect(full, entry, included, excluded);
    } else if (ALWAYS_EXCLUDED.has(path.basename(entry))) {
      excluded.push(entry);
    } else {
      included.push(entry);
    }
  }
  return {
    included: [...new Set(included)].sort(compare),
    excluded: [...new Set(excluded)].sort(compare),
  };
}

/** bin / main / exports が指す先を集める（"./dist/x.js" と "dist/x.js" を同じ形に揃える） */
function entryTargets(manifest: Manifest): string[] {
  const targets: string[] = [];
  if (typeof manifest.bin === "string") {
    targets.push(manifest.bin);
  } else if (manifest.bin !== undefined) {
    targets.push(...Object.values(manifest.bin));
  }
  if (typeof manifest.main === "string") targets.push(manifest.main);
  if (typeof manifest.exports === "string") {
    targets.push(manifest.exports);
  } else if (manifest.exports !== undefined) {
    for (const value of Object.values(manifest.exports)) {
      if (typeof value === "string") targets.push(value);
    }
  }
  return targets.map((target) => target.replace(/^\.\//, ""));
}

const packageDir = process.argv[2];
if (packageDir === undefined) {
  console.error("使い方: npx tsx src/review05/q3-check-dist.ts <パッケージのディレクトリ>");
  process.exit(2);
}

const manifest = JSON.parse(
  fs.readFileSync(path.join(packageDir, "package.json"), "utf8"),
) as Manifest;
const { included, excluded } = buildFileList(packageDir, manifest);

console.log(`[gate] 対象: ${packageDir}`);
console.log(`[gate] パッケージ: ${manifest.name}@${manifest.version}`);
console.log(`[gate] files: ${(manifest.files ?? []).join(", ")}`);
console.log(`[gate] 配布対象 ${included.length} 件`);
for (const file of included) console.log(`        ${file}`);
console.log(`[gate] 常に除外 ${excluded.length} 件（npm の規則）`);
for (const file of excluded) console.log(`        ${file}`);

const problems: string[] = [];
const warnings: string[] = [];

for (const file of included) {
  for (const rule of FORBIDDEN_PATHS) {
    if (rule.re.test(file)) {
      problems.push(`配布してはいけないファイルが含まれています: ${file}（${rule.label}）`);
    }
  }
}

for (const target of entryTargets(manifest)) {
  if (!included.includes(target)) {
    problems.push(`package.json が指すファイルが配布物にありません: ${target}`);
  }
}

for (const file of included) {
  const full = path.join(packageDir, file);
  if (fs.statSync(full).size > MAX_SCAN_BYTES) continue;
  const text = fs.readFileSync(full, "utf8");
  for (const rule of SECRET_CONTENTS) {
    if (rule.re.test(text)) {
      // 一致した値は出さない。検査ツール自身が秘密を漏らしてはいけない
      problems.push(`本文に秘密情報らしき文字列が見つかりました: ${rule.label}（${file}）`);
    }
  }
}

for (const expected of ["README.md", "LICENSE"]) {
  if (!included.includes(expected)) {
    warnings.push(`${expected} が配布物にありません（利用者が使い方とライセンスを知れません）`);
  }
}

for (const warning of warnings) console.log(`WARN: ${warning}`);
if (problems.length > 0) {
  for (const problem of problems) console.log(`NG: ${problem}`);
  console.log(`NG: ${problems.length} 件の問題が見つかりました。この配布物を公開してはいけません。`);
  process.exit(1);
}
console.log("OK: 配布物の中身に問題は見つかりませんでした");
