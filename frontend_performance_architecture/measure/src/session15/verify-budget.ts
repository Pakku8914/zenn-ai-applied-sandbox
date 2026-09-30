import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  BUDGETS,
  CONDITIONS_LABEL,
  KB,
  appendRecord,
  diffRecords,
  evaluate,
  formatDiff,
  formatResults,
  historyFile,
  loadHistory,
  measureRecord,
  passed,
  type BudgetRecord,
} from './budget.ts';

/**
 * S15：パフォーマンス予算の検査が「出発点は合格・太らせた版は不合格」を正しく判定することを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session15/verify-budget.ts
 * 初期 JS（バイト数）は決定的なので予算との大小で、LCP（時間）は2ページの大小関係で判定する。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const MAIN_URL = `${TARGET}/`;
const FAT_URL = `${TARGET}/pages/s15-fat/`;
const failures: string[] = [];
function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}
const fmt = (n: number): string => n.toLocaleString('en-US');

// 1. 判定と差分の純粋関数（固定値）
console.log('--- 判定と差分（固定値） ---');
check('予算は 250KB（1KB = 1,000 バイト）と 1,000ms', BUDGETS[0]?.max === 250 * KB && 250 * KB === 250_000 && BUDGETS[1]?.max === 1_000);
check('上限ちょうどは合格', passed(evaluate({ jsBytes: 250_000, LCP: 1_000 })));
const over = evaluate({ jsBytes: 250_001, LCP: 999 });
check('1 バイトでも超えたら不合格', over[0]?.status === 'fail' && over[1]?.status === 'pass' && !passed(over));
const missing = evaluate({ jsBytes: 201_311 });
check('測れなかった指標は合格にしない', missing[1]?.status === 'missing' && !passed(missing));
let rejected = false;
try {
  historyFile('/tmp', '../etc/passwd');
} catch {
  rejected = true;
}
check('記録の名前にパスとして危険な文字を受け付けない', rejected);
const fixture = (jsBytes: number, LCP: number): BudgetRecord => ({
  name: 'catalog', url: MAIN_URL, measuredAt: '2026-09-30T00:00:00.000Z', commit: 'fixture',
  conditions: CONDITIONS_LABEL, runs: 3, median: { jsBytes, LCP }, samples: {},
});
const small = diffRecords(fixture(201_311, 700), fixture(202_000, 800));
check('小さな増加（+689 バイト・+14%）は要確認にしない', small.every((row) => !row.regressed));
const big = diffRecords(fixture(201_311, 700), fixture(322_000, 900));
check('大きな増加（+120,689 バイト・+29%）は要確認', big.every((row) => row.regressed));
check('前回が無ければ差は出さない', diffRecords(undefined, fixture(1, 1)).every((row) => row.delta === undefined && !row.regressed));

// 2. 実測：出発点は予算内、太らせた版は初期 JS の予算違反
console.log(`\n--- 実測（${CONDITIONS_LABEL}・各3回の中央値） ---`);
const main = await measureRecord('catalog', MAIN_URL, 3);
const fat = await measureRecord('catalog', FAT_URL, 3);
const mainResults = evaluate(main.median);
const fatResults = evaluate(fat.median);
console.log(`[出発点] ${MAIN_URL}\n${formatResults(mainResults)}`);
console.log(`[太らせた版] ${FAT_URL}\n${formatResults(fatResults)}\n`);
const mainLcp = main.samples.LCP ?? [];
console.log(`出発点の各回: 初期 JS ${(main.samples.jsBytes ?? []).map(fmt).join(' / ')} バイト、LCP ${mainLcp.map((v) => `${fmt(Math.round(v))}ms`).join(' / ')}`);
check('出発点はすべての予算内', passed(mainResults));
check('太らせた版は初期 JS の予算違反', fatResults.find((r) => r.metric === 'jsBytes')?.status === 'fail');
const added = (fat.median.jsBytes ?? 0) - (main.median.jsBytes ?? 0);
check('初期 JS の差は 100,000 バイト以上（react-dom/server が入った）', added >= 100_000, `+${fmt(added)} バイト`);
check('初期 JS は3回とも同じ値（決定的）', new Set(main.samples.jsBytes).size === 1 && new Set(fat.samples.jsBytes).size === 1);
check('LCP は3回とも取れている', mainLcp.length === 3 && (fat.samples.LCP ?? []).length === 3);
const mainLcpMedian = main.median.LCP ?? Number.NaN;
const fatLcpMedian = fat.median.LCP ?? Number.NaN;
check('LCP 中央値は太らせた版のほうが大きい', fatLcpMedian > mainLcpMedian, `${fmt(Math.round(mainLcpMedian))}ms → ${fmt(Math.round(fatLcpMedian))}ms`);

// 3. 履歴と差分：同じ名前で「出発点 → 太らせた版」の順に記録すると、差分に回帰が出る
console.log('\n--- 履歴と差分 ---');
const dir = join(mkdtempSync(join(tmpdir(), 's15-budget-')), 'history');
try {
  appendRecord(dir, main);
  check('履歴ディレクトリに .gitignore が作られる', existsSync(join(dir, '.gitignore')));
  const previous = loadHistory(dir, 'catalog').at(-1);
  console.log(formatDiff(previous, fat));
  check('初期 JS の差が要確認になる', diffRecords(previous, fat).find((row) => row.metric === 'jsBytes')?.regressed === true);

  // 4. CI の入口：違反なら終了コード 1、予算内なら 0
  console.log('\n--- check-budget.ts の終了コード ---');
  const run = (target: string, runs: string) =>
    spawnSync(process.execPath, ['--experimental-strip-types', join(import.meta.dirname, 'check-budget.ts'), target], {
      env: { ...process.env, BUDGET_RUNS: runs, BUDGET_HISTORY_DIR: dir },
      encoding: 'utf8',
    });
  const fatRun = run(`catalog=${FAT_URL}`, '1');
  check('太らせた版では終了コード 1', fatRun.status === 1, `終了コード ${fatRun.status}`);
  check('出力に前回との差の表が含まれる', fatRun.stdout.includes('| 初期 JS |'));
  const mainRun = run(`catalog=${MAIN_URL}`, '3');
  check('出発点では終了コード 0', mainRun.status === 0, `終了コード ${mainRun.status}`);
  const badName = run(`../x=${MAIN_URL}`, '1');
  check('使えない名前では計測せずに終了コード 2', badName.status === 2, `終了コード ${badName.status}`);
  check('履歴には3件が追記されている', loadHistory(dir, 'catalog').length === 3);
} finally {
  rmSync(join(dir, '..'), { recursive: true, force: true });
}

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS15 パフォーマンス予算の検証に成功しました。');
