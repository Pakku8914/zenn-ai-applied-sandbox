import { CLS_RUNS, RUNS, TABLE_HEADER, conditionsLabel, formatRow, measurePage, pageUrl } from './helpers.ts';

/**
 * 最終プロジェクト：ページごとの基準値を同じ条件でまとめて取り、改善レポートに貼れる表を出す（判定はしない）。
 * 実行: docker compose exec measure node --experimental-strip-types src/final/measure-page.ts final-start
 *       docker compose exec measure node --experimental-strip-types src/final/measure-page.ts final-start final-mine
 * ページ名は app/pages/ の下のディレクトリ名。1 ページあたり数分かかる（出題版は全件描画のため特に長い）。
 */
const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;
const names = process.argv.slice(2);
const targets = names.length > 0 ? names : ['final-start'];
for (const name of targets) {
  if (!NAME_PATTERN.test(name)) {
    console.error(`ページ名「${name}」は使えません（英小文字・数字・ハイフンのみ）`);
    process.exit(2);
  }
}

console.log(`計測条件: ${conditionsLabel()}（LCP・INP・初期 JS は各${RUNS}回、CLS は各${CLS_RUNS}回の中央値。INP は 40ms 未満なら 40ms として表示）\n`);
const rows: string[] = [];
for (const name of targets) {
  console.log(`計測中: ${pageUrl(name)}`);
  rows.push(formatRow(name, await measurePage(pageUrl(name))));
}
console.log(`\n${TABLE_HEADER}`);
for (const row of rows) console.log(row);
