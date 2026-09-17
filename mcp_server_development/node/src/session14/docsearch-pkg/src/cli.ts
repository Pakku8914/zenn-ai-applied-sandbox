#!/usr/bin/env node
/**
 * docsearch-mcp ― 実行可能エントリーポイント（package.json の bin から起動される）
 *
 * 起動例：
 *   docsearch-mcp --docs-root /abs/path/to/docs
 *   DOCSEARCH_ROOT=/abs/path/to/docs docsearch-mcp
 *
 * このファイルの責務は 3 つだけです。
 *   ① 引数と環境変数から「ユーザー設定項目」を読み取る
 *   ② 設定が使える状態かを検査し、駄目なら人間に読めるエラーを stderr に出して落ちる
 *   ③ サーバー定義を組み立てて stdio に繋ぐ
 *
 * stdout は JSON-RPC の通信路そのものなので、サーバーとして動き始めたあとは
 * 絶対に書きません（--help / --version は「サーバーではないモード」なので stdout でよい）。
 */
import fs from "node:fs";
import { createRequire } from "node:module";

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { resolveDocsRoot } from "./config.js";
import { createDocSearchServer } from "./create-server.js";

// 版番号を package.json から読む。ハードコードすると必ず食い違う（12 節）。
// dist/cli.js から見た ../package.json はパッケージのルート。src/cli.ts から見ても同じ位置。
const requireJson = createRequire(import.meta.url);
const pkg = requireJson("../package.json") as { name: string; version: string };

const HELP = `${pkg.name} ${pkg.version}
社内 Markdown を全文検索する読み取り専用の MCP サーバー（stdio）です。

使い方:
  ${pkg.name} --docs-root <検索対象ディレクトリ>
  DOCSEARCH_ROOT=<検索対象ディレクトリ> ${pkg.name}

オプション:
  --docs-root <dir>   検索対象の Markdown が置かれたディレクトリ（絶対パスを推奨）
  -h, --help          この説明を表示する
  -v, --version       版を表示する

ホストからの起動例:
  { "command": "npx", "args": ["-y", "${pkg.name}", "--docs-root", "/abs/path/to/docs"] }

手で起動すると何も表示されずに止まって見えますが異常ではありません。
標準入力から JSON-RPC のリクエストが来るのを待っています（Ctrl+C で終了）。
`;

type Options = {
  readonly help: boolean;
  readonly version: boolean;
  readonly docsRoot: string | undefined;
  readonly invalid: string | undefined;
};

function parseArgs(argv: readonly string[]): Options {
  let help = false;
  let version = false;
  let docsRoot: string | undefined;
  let invalid: string | undefined;

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i] ?? "";
    if (token === "-h" || token === "--help") {
      help = true;
    } else if (token === "-v" || token === "--version") {
      version = true;
    } else if (token === "--docs-root") {
      // 次のトークンを値として取る。無ければ不正な指定
      const value = argv[i + 1];
      if (value === undefined || value.startsWith("-")) {
        invalid ??= "--docs-root には値が必要です";
      } else {
        docsRoot = value;
        i += 1;
      }
    } else if (token.startsWith("--docs-root=")) {
      docsRoot = token.slice("--docs-root=".length);
    } else if (token.startsWith("-")) {
      // 知らないオプションを黙って無視しない。設定ミスに気づけなくなる
      invalid ??= `知らないオプションです: ${token}`;
    } else if (docsRoot === undefined) {
      // 位置引数も受け付ける（開発中の起動方法との互換）
      docsRoot = token;
    } else {
      invalid ??= `引数が多すぎます: ${token}`;
    }
  }
  return { help, version, docsRoot, invalid };
}

function isReadableDirectory(target: string): boolean {
  try {
    return fs.statSync(target).isDirectory();
  } catch {
    return false;
  }
}

const options = parseArgs(process.argv.slice(2));

if (options.help) {
  process.stdout.write(HELP);
  process.exit(0);
}
if (options.version) {
  process.stdout.write(`${pkg.name} ${pkg.version}\n`);
  process.exit(0);
}
if (options.invalid !== undefined) {
  process.stderr.write(`${options.invalid}\n\n${HELP}`);
  process.exit(2);
}

// 明示指定があったかを先に判定する。配布物では「既定値」に頼れない（7 節）
const fromEnv = process.env["DOCSEARCH_ROOT"] ?? "";
const explicit = options.docsRoot !== undefined || fromEnv.length > 0;

// 解決そのものは中間プロジェクト1 の仕組み（引数 → 環境変数 → 既定値）に載せる
const docsRoot = resolveDocsRoot(
  options.docsRoot === undefined ? [] : [options.docsRoot],
  process.env,
);

if (!explicit) {
  process.stderr.write(
    `${pkg.name}: 検索対象ディレクトリが指定されていません。\n` +
      "--docs-root <dir> を渡すか、環境変数 DOCSEARCH_ROOT を設定してください。\n" +
      `詳しくは ${pkg.name} --help を参照してください。\n`,
  );
  process.exit(2);
}
if (!isReadableDirectory(docsRoot)) {
  process.stderr.write(
    `${pkg.name}: 検索対象ディレクトリが見つかりません: ${docsRoot}\n` +
      "相対パスを渡した場合、基準になるのはホストが決めた作業ディレクトリです。絶対パスを推奨します。\n",
  );
  process.exit(2);
}

const server = createDocSearchServer({ docsRoot, serverVersion: pkg.version });
await server.connect(new StdioServerTransport());

// 起動ログは stderr。ここで stdout に書くと最初の JSON-RPC 電文が壊れる
process.stderr.write(`[${pkg.name}] v${pkg.version} / docsRoot=${docsRoot}\n`);
