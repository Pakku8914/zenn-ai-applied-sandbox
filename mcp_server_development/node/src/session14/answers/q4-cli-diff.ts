/** 検索件数の既定値と上限。ドメイン層の MAX_LIMIT と揃えておく */
const DEFAULT_MAX_RESULTS = 5;
const MAX_ALLOWED_RESULTS = 20;

type MaxResults =
  | { readonly ok: true; readonly value: number }
  | { readonly ok: false; readonly message: string };

/**
 * ① 引数 --max-results → ② 環境変数 DOCSEARCH_MAX_RESULTS → ③ 既定値 5
 *
 * 環境変数は必ず文字列で届きます。数値に見えない値・範囲外の値は
 * 「無言で既定値に戻す」のではなく、起動時のエラーにします。
 * 無言で戻すと、利用者は「設定したのに効かない」を延々と疑うことになります。
 */
function resolveMaxResults(cliValue: string | undefined, env: NodeJS.ProcessEnv): MaxResults {
  const raw = (cliValue ?? env["DOCSEARCH_MAX_RESULTS"] ?? "").trim();
  if (raw.length === 0) {
    return { ok: true, value: DEFAULT_MAX_RESULTS };
  }
  if (!/^[0-9]+$/.test(raw)) {
    return { ok: false, message: `--max-results には整数を指定してください（受け取った値: ${raw}）` };
  }
  const value = Number.parseInt(raw, 10);
  if (value < 1 || value > MAX_ALLOWED_RESULTS) {
    return {
      ok: false,
      message: `--max-results は 1 以上 ${MAX_ALLOWED_RESULTS} 以下で指定してください（受け取った値: ${value}）`,
    };
  }
  return { ok: true, value };
}

// parseArgs() の分岐に追加する（--max-results 3 と --max-results=3 の両方を受ける）
// } else if (token === "--max-results") {
//   const value = argv[i + 1];
//   if (value === undefined || value.startsWith("-")) {
//     invalid ??= "--max-results には値が必要です";
//   } else { maxResults = value; i += 1; }
// } else if (token.startsWith("--max-results=")) {
//   maxResults = token.slice("--max-results=".length);

// 起動処理の末尾に追加する（cli.ts 側に書く。このファイル単体では options / pkg が無いので
// コメントにしてあります。そのまま cli.ts に移してください）
//
// const maxResults = resolveMaxResults(options.maxResults, process.env);
// if (!maxResults.ok) {
//   process.stderr.write(`${pkg.name}: ${maxResults.message}\n`);
//   process.exit(2);
// }
// process.stderr.write(
//   `[${pkg.name}] v${pkg.version} / docsRoot=${docsRoot} / maxResults=${maxResults.value}\n`,
// );
