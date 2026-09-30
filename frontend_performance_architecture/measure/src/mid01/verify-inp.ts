import { measureMedian, median } from '../vitals-client.ts';
import {
  INP_REPORT_THRESHOLD_MS,
  KEYWORD,
  MATCHED,
  SEARCH_LOG_MS,
  chartClickInp,
  conditionsLabel,
  createChecker,
  ms,
  n,
  pageUrl,
  typingRun,
  type TypingRun,
} from './lab.ts';

/**
 * 中間プロジェクト：入力応答（INP）の問題と、直さない判断（一覧のメモ化・グラフのボタン）を確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/mid01/verify-inp.ts
 * 検索ログの送信回数・行数は完全一致で、INP と処理時間は大小関係と比率で判定する。
 */
const PAGES = ['mid01-slow', 'mid01-fixed'] as const;
const { check, finish } = createChecker();

console.log(`計測条件: ${conditionsLabel()}（INP は各3回の中央値）`);
console.log(`入力: #keyword に「${KEYWORD}」（pressSequentially）\n`);

const inp: Record<string, number> = {};
const diag: Record<string, TypingRun> = {};
for (const name of PAGES) {
  const { median: m } = await measureMedian(pageUrl(name), { runs: 3, input: { selector: '#keyword', value: KEYWORD } });
  // 3 回とも 40ms 未満で報告されなかったときは、上限の 40ms として扱う（改善版に有利にならない側に倒す）
  inp[name] = m.INP ?? INP_REPORT_THRESHOLD_MS;
  diag[name] = await typingRun(pageUrl(name));
  const d = diag[name]!;
  console.log(
    `${name.padEnd(12)}: 入力 INP ${ms(inp[name])} / 最長の処理時間 ${ms(d.maxProcessing)}` +
      ` / 検索ログ ${d.searchLogs.length} 回（${d.searchLogs.join('・')}） / 入力後の行数 ${n(d.liAfter)}`,
  );
}

// 「グラフを表示」のクリックは問題ではないことを確かめる（出題版で 3 回）
const clicks: number[] = [];
for (let i = 0; i < 3; i += 1) clicks.push((await chartClickInp(pageUrl('mid01-slow'))) ?? INP_REPORT_THRESHOLD_MS);
const clickInp = median(clicks);
console.log(`mid01-slow  : 「グラフを表示」クリックの INP ${ms(clickInp)}（各回 ${clicks.map((v) => ms(v)).join(' / ')}）\n`);

const slow = inp['mid01-slow']!;
const fixed = inp['mid01-fixed']!;
const slowDiag = diag['mid01-slow']!;
const fixedDiag = diag['mid01-fixed']!;

// 問題が計測で見えること
check('出題版の入力 INP が 200ms 以上（good の境界を超えている）', slow >= 200, ms(slow));
check(
  `出題版では処理時間が検索ログの占有時間（${SEARCH_LOG_MS}ms）以上＝入力ハンドラーの中が長い`,
  slowDiag.maxProcessing >= SEARCH_LOG_MS,
  ms(slowDiag.maxProcessing),
);
check('出題版は 1 文字ごとに検索ログを送る（3 回）', slowDiag.searchLogs.join('|') === '商|商品|商品1', slowDiag.searchLogs.join('・'));

// 改善したこと
check('模範解答版の入力 INP 中央値が出題版の 0.5 倍以下', fixed <= slow * 0.5, `${(fixed / slow).toFixed(2)} 倍`);
check('模範解答版の入力 INP が 200ms 未満（good）', fixed < 200, ms(fixed));
check(`模範解答版の処理時間は ${SEARCH_LOG_MS}ms 未満`, fixedDiag.maxProcessing < SEARCH_LOG_MS, ms(fixedDiag.maxProcessing));
check('模範解答版は入力が止まってから 1 回だけ送る', fixedDiag.searchLogs.join('|') === '商品1', fixedDiag.searchLogs.join('・'));

// 機能を壊していないこと（決定的な値は完全一致）
for (const name of PAGES) {
  check(`${name}: 入力後の行数が ${n(MATCHED)}`, diag[name]!.liAfter === MATCHED, n(diag[name]!.liAfter));
}

// 直さない判断の根拠：一覧はメモ化していないが、模範解答版の入力 INP は good。グラフのクリックも good
check('「グラフを表示」クリックの INP は 200ms 未満（直す対象ではない）', clickInp < 200, ms(clickInp));

finish('中間プロジェクトの INP');
