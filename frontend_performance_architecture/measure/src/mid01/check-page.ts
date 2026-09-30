import { measureMedian, median } from '../vitals-client.ts';
import {
  INP_REPORT_THRESHOLD_MS,
  KEYWORD,
  MATCHED,
  clsOnce,
  conditionsLabel,
  createChecker,
  ms,
  n,
  pageUrl,
  typingRun,
} from './lab.ts';

/**
 * 中間プロジェクト：自分の改善版ページが、出題版に対して改善の基準を満たしているかを判定する（回帰検知用）。
 * 実行: docker compose exec measure node --experimental-strip-types src/mid01/check-page.ts mid01-mine
 *       （引数を省略すると模範解答版 mid01-fixed を判定する。所要時間は約 3 分）
 * 判定規則は verify-*.ts と同じ。時間は比率で、行数・送信回数は完全一致・下限で判定する。
 */
const BASE = 'mid01-slow';
const target = process.argv[2] ?? 'mid01-fixed';
const CLS_RUNS = 5;
const { check, finish } = createChecker();

type Summary = { lcp: number; inp: number; cls: number };

async function summarize(name: string): Promise<Summary> {
  const load = await measureMedian(pageUrl(name), { runs: 3 });
  const typing = await measureMedian(pageUrl(name), { runs: 3, input: { selector: '#keyword', value: KEYWORD } });
  const cls: number[] = [];
  for (let i = 0; i < CLS_RUNS; i += 1) cls.push(await clsOnce(pageUrl(name)));
  return {
    lcp: load.median.LCP ?? Number.NaN,
    // 40ms 未満で報告されなかったときは 40ms として扱う（改善版に有利にならない側に倒す）
    inp: typing.median.INP ?? INP_REPORT_THRESHOLD_MS,
    cls: median(cls),
  };
}

console.log(`計測条件: ${conditionsLabel()}（LCP・INP は各3回、CLS は各${CLS_RUNS}回の中央値）`);
const before = await summarize(BASE);
const after = await summarize(target);
console.table([
  { ページ: BASE, LCP: ms(before.lcp), CLS: before.cls, 入力INP: ms(before.inp) },
  { ページ: target, LCP: ms(after.lcp), CLS: after.cls, 入力INP: ms(after.inp) },
]);

check('LCP が出題版の 0.7 倍以下', after.lcp <= before.lcp * 0.7, `${(after.lcp / before.lcp).toFixed(2)} 倍`);
check('CLS が 0.1 未満', after.cls < 0.1, String(after.cls));
check('CLS が出題版の 0.2 倍以下', after.cls <= before.cls * 0.2, `${(after.cls / before.cls).toFixed(2)} 倍`);
check('入力 INP が 200ms 未満', after.inp < 200, ms(after.inp));
check('入力 INP が出題版の 0.5 倍以下', after.inp <= before.inp * 0.5, `${(after.inp / before.inp).toFixed(2)} 倍`);

// 機能を壊していないこと・外せない要件を消していないこと
const diag = await typingRun(pageUrl(target));
check(`入力後の行数が ${n(MATCHED)}`, diag.liAfter === MATCHED, n(diag.liAfter));
check('検索ログを消していない（入力後に 1 回以上送っている）', diag.searchLogs.length >= 1, `${diag.searchLogs.length} 回`);
check(`最後に送った検索ログが入力し終えた「${KEYWORD}」`, diag.searchLogs.at(-1) === KEYWORD, diag.searchLogs.join('・'));

finish(`${target} の改善基準`);
