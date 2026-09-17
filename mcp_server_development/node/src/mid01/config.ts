/**
 * 検索対象ディレクトリの決定
 *
 * 「あとで外から変えたくなる値」は最初から外から入れられる形にしておきます。
 * この 1 か所のおかげで、以降のセッションで次の 4 つがコード変更なしにできます。
 *   ① シンボリックリンクを仕込んだ実験用ディレクトリで動かす（問題8）
 *   ② roots で受け取ったディレクトリに切り替える（セッション9）
 *   ③ 悪意ある文書を混ぜたディレクトリを試す（セッション15）
 *   ④ npx docsearch ./docs として配る（セッション14）
 */
import path from "node:path";

/** 既定の検索対象ディレクトリ（サンドボックスの /app からの相対パス） */
export const DEFAULT_DOCS_ROOT = "src/mid01/docs";

/**
 * ① コマンドライン第 1 引数 → ② 環境変数 DOCSEARCH_ROOT → ③ 既定値 の順で解決する。
 * 引数を受け取れる形にしているのは、テストから別のディレクトリを渡せるようにするため。
 */
export function resolveDocsRoot(
  argv: readonly string[] = process.argv.slice(2),
  env: NodeJS.ProcessEnv = process.env,
): string {
  const fromArgv = argv[0];
  if (fromArgv !== undefined && fromArgv.length > 0) {
    return path.resolve(fromArgv);
  }
  const fromEnv = env["DOCSEARCH_ROOT"];
  if (fromEnv !== undefined && fromEnv.length > 0) {
    return path.resolve(fromEnv);
  }
  return path.resolve(DEFAULT_DOCS_ROOT);
}
