import { measureMedian, median } from '../vitals-client.ts';
import { INP_REPORT_THRESHOLD_MS, KEYWORD, chartClickInp, clsOnce, conditionsLabel, ms, n, pageUrl, typingRun } from './lab.ts';

/**
 * 中間プロジェクトの診断用：1 ページぶんの指標を同じ条件でまとめて計測し、報告書にそのまま貼れる表の 1 行を出す。
 * 判定はしない（verify ではない）。自分で作ったページの前後比較に使う。
 * 実行: docker compose exec measure node --experimental-strip-types src/mid01/measure-page.ts mid01-slow
 *       （出発点を測るときは root を渡す。所要時間は 1 ページ約 1〜2 分）
 */
const name = process.argv[2];
if (!name) {
  console.error('使い方: node --experimental-strip-types src/mid01/measure-page.ts <ページ名 | root>');
  process.exit(1);
}
const url = pageUrl(name);
const RUNS = 3;

const load = await measureMedian(url, { runs: RUNS });
const typing = await measureMedian(url, { runs: RUNS, input: { selector: '#keyword', value: KEYWORD } });

const clsValues: number[] = [];
const clickValues: number[] = [];
for (let i = 0; i < RUNS; i += 1) {
  clsValues.push(await clsOnce(url));
  clickValues.push((await chartClickInp(url)) ?? INP_REPORT_THRESHOLD_MS);
}
const diag = await typingRun(url);

console.log(`計測条件: ${conditionsLabel()}（各${RUNS}回の中央値。INP は 40ms 未満なら 40ms として表示）`);
console.log(`対象: ${url}\n`);
console.log('| ページ | LCP | CLS | 入力 INP | クリック INP | 初期 JS | 最長の処理時間 | 検索ログ |');
console.log('| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |');
console.log(
  `| ${name} | ${ms(load.median.LCP)} | ${median(clsValues)} | ${ms(typing.median.INP ?? INP_REPORT_THRESHOLD_MS)}` +
    ` | ${ms(median(clickValues))} | ${n(load.median.jsBytes ?? 0)} バイト | ${ms(diag.maxProcessing)} | ${diag.searchLogs.length} 回 |`,
);
