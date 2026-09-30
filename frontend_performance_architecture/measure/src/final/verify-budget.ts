import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  BUDGETS,
  KB,
  appendRecord,
  diffRecords,
  evaluate,
  formatDiff,
  formatResults,
  loadHistory,
  measureRecord,
  passed,
} from '../session15/budget.ts';
import { DONE, START, conditionsLabel, createChecker } from './helpers.ts';

/**
 * 最終プロジェクト：S15 のパフォーマンス予算を、模範解答版は満たし、出題版は破ることを確かめる。
 * あわせて、CI の入口（check-budget.ts）が出題版で終了コード 1 を返す＝「悪化を入れたら CI が落ちる」ことを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/final/verify-budget.ts
 */
const { check, finish } = createChecker();

check(
  '予算は S15 と同じ（初期 JS 250,000 バイト・LCP 中央値 1,000ms）',
  BUDGETS.length === 2 && BUDGETS[0]?.max === 250 * KB && BUDGETS[1]?.max === 1_000,
);

console.log(`\n--- 実測（${conditionsLabel()}・各3回の中央値） ---`);
const done = await measureRecord('final', DONE, 3);
const start = await measureRecord('final', START, 3);
const doneResults = evaluate(done.median);
const startResults = evaluate(start.median);
console.log(`[模範解答版] ${DONE}\n${formatResults(doneResults)}`);
console.log(`[出題版] ${START}\n${formatResults(startResults)}\n`);
check('模範解答版はすべての予算内', passed(doneResults));
check('出題版は初期 JS の予算違反', startResults.find((r) => r.metric === 'jsBytes')?.status === 'fail');

// 履歴と差分：模範解答版を「前回」として記録し、出題版（＝悪化を入れた状態）と比べる
console.log('--- 履歴と差分 ---');
const dir = join(mkdtempSync(join(tmpdir(), 'final-budget-')), 'history');
try {
  appendRecord(dir, done);
  const previous = loadHistory(dir, 'final').at(-1);
  console.log(formatDiff(previous, start));
  check('差分で初期 JS が要確認になる', diffRecords(previous, start).find((row) => row.metric === 'jsBytes')?.regressed === true);

  // CI の入口：予算内なら終了コード 0、違反なら 1
  console.log('\n--- check-budget.ts の終了コード ---');
  const run = (target: string, runs: string) =>
    spawnSync(process.execPath, ['--experimental-strip-types', join(import.meta.dirname, '../session15/check-budget.ts'), target], {
      env: { ...process.env, BUDGET_RUNS: runs, BUDGET_HISTORY_DIR: dir },
      encoding: 'utf8',
    });
  const doneRun = run(`final-done=${DONE}`, '3');
  check('模範解答版では終了コード 0', doneRun.status === 0, `終了コード ${doneRun.status}`);
  const startRun = run(`final-start=${START}`, '1');
  check('出題版では終了コード 1（CI が落ちる）', startRun.status === 1, `終了コード ${startRun.status}`);
  check('出題版の出力に初期 JS の NG 行がある', startRun.stdout.includes('NG  初期 JS'));
} finally {
  rmSync(join(dir, '..'), { recursive: true, force: true });
}

finish('最終プロジェクトのパフォーマンス予算');
