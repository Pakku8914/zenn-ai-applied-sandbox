/**
 * リリース候補ディレクトリを生成する（問題3(a)）
 *
 *   docker compose exec node npx tsx src/review05/q3-make-candidate.ts
 *   docker compose exec node npx tsx src/review05/q3-make-candidate.ts --fixed
 *
 * --fixed を付けると、問題3(c) で修正したあとの状態を生成します。
 *
 * ★ ここに書く「秘密情報」はすべて架空の値です。本物のトークン・鍵・社内ホスト名を
 *   絶対に書かないでください。テスト用の値もリポジトリに残り、CI のログに出ます。
 */
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve("src/review05/release-candidate");
const fixed = process.argv.includes("--fixed");

/** 架空のトークン。実在しません（検査スクリプトが検出することの確認に使います） */
const FAKE_TOKEN = "ghp_R05ExampleTokenAbcd1234";

const manifest = {
  name: "approval-mcp",
  version: "0.1.0",
  type: "module",
  bin: { "approval-mcp": "dist/cli.js" },
  // ★ 修正前はビルド前のパスを指したまま（実際によくある事故）
  main: fixed ? "dist/index.js" : "src/index.js",
  files: ["dist", "README.md", "LICENSE"],
  license: "MIT",
};

type CandidateFile = { readonly rel: string; readonly body: string };

/** 修正後も残るファイル（9 件） */
const BASE_FILES: readonly CandidateFile[] = [
  { rel: "package.json", body: `${JSON.stringify(manifest, null, 2)}\n` },
  { rel: "README.md", body: "# approval-mcp\n\n社内申請ワークフローの MCP サーバーです。\n" },
  { rel: "LICENSE", body: "MIT License\n" },
  { rel: "dist/cli.js", body: "#!/usr/bin/env node\nimport './index.js';\n" },
  { rel: "dist/index.js", body: "export const name = 'approval-mcp';\n" },
  { rel: "dist/create-server.js", body: "export function createServer() { return null; }\n" },
  { rel: "dist/config.js", body: "export const defaultLimit = 3;\n" },
  // npm が常に除外する名前。files で dist を許可しても配布物には入らない
  { rel: "dist/.npmrc", body: "//registry.example.com/:_authToken=dummy-value-not-real\n" },
  { rel: "src/create-server.ts", body: "export function createServer(): null {\n  return null;\n}\n" },
];

/** 修正前だけ置く「混ざってはいけないもの」（2 件） */
const LEAKY_FILES: readonly CandidateFile[] = [
  {
    rel: "dist/.env",
    body: `APPROVAL_API_TOKEN=${FAKE_TOKEN}\nAUDIT_LOG_PEPPER=0123456789abcdef\n`,
  },
  {
    rel: "dist/dev-notes.md",
    body:
      "# 開発メモ（社外に出さないこと）\n\n" +
      `- 疎通確認では api_key = "${FAKE_TOKEN}" を使った\n` +
      "- 本番切り替えは 2026-09-01\n",
  },
];

const FILES: readonly CandidateFile[] = fixed ? BASE_FILES : [...BASE_FILES, ...LEAKY_FILES];

fs.rmSync(ROOT, { recursive: true, force: true });
for (const file of FILES) {
  const full = path.join(ROOT, file.rel);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, file.body, "utf8");
}
console.log(`作成しました: ${path.relative(process.cwd(), ROOT)}（${FILES.length} ファイル）`);
