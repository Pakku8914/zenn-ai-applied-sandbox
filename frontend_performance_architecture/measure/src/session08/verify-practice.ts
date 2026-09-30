import { CONDITIONS, median, withPage } from '../vitals-client.ts';
import { INP_REPORT_THRESHOLD_MS, ms, n, typeAndCount, type TypingRun } from './render-count.ts';

/**
 * S08 練習問題の解答ページ（問題4・問題5・問題6）を検証する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session08/verify-practice.ts
 * 回数は完全一致で、INP は大小関係と比率で判定する。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const RUNS = 3;
const MATCHED = 11_111;
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

async function measure(page: string, runs = RUNS): Promise<{ inp: number; runs: TypingRun[] }> {
  const results: TypingRun[] = [];
  for (let i = 0; i < runs; i += 1) {
    results.push(await withPage((p) => typeAndCount(p, `${TARGET}/pages/${page}/`, MATCHED)));
  }
  const inp = median(results.map((r) => r.inp ?? INP_REPORT_THRESHOLD_MS));
  const r0 = results[0]!;
  console.log(
    `${page.padEnd(22)}: 入力 INP ${ms(inp)} / 行の実行 入力中 ${n(r0.rowsWhileTyping)}・選択2回 ${n(r0.rowsWhileSelecting)}` +
      ` / 選択2回でのカタログの実行 ${r0.catalogWhileSelecting}`,
  );
  return { inp, runs: results };
}

const { cpuThrottlingRate, network } = CONDITIONS;
console.log(
  `計測条件: CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド（各${RUNS}回の中央値）`,
);

const bad = await measure('s08-bad-20k');
const inline = await measure('s08-memo-inline-20k');
const fixed = await measure('s08-practice-fixed');
const memo = await measure('s08-memo-20k', 1);
const deferred = await measure('s08-practice-deferred');
console.log('');

// 問題4：onSelect を固定すると、入力中の行の実行は 0 回・選択2回で 3 回
check('問題4: 直した版の入力中の行の実行が 0 回', fixed.runs.every((r) => r.rowsWhileTyping === 0));
check('問題4: 直した版の選択2回の行の実行が 3 回', fixed.runs.every((r) => r.rowsWhileSelecting === 3));
check('問題4: 直した版の入力 INP が memo だけの版より小さい', fixed.inp < inline.inp, `${ms(inline.inp)} → ${ms(fixed.inp)}`);

// 問題5：選択のたびに親（カタログ）は再レンダリングされる。useMemo が無ければ、その回数だけ絞り込みが走る
check('問題5: Bad 版の選択2回の行の実行が 22,222 回', bad.runs.every((r) => r.rowsWhileSelecting === 22_222));
check('問題5: メモ化版の選択2回の行の実行が 3 回', memo.runs.every((r) => r.rowsWhileSelecting === 3));
check('問題5: メモ化版でも選択2回でカタログの本体は 2 回実行される', memo.runs.every((r) => r.catalogWhileSelecting === 2));

// 問題6：一覧を memo で包んだ useDeferredValue 版
check('問題6: 自作の useDeferredValue 版の入力中の行の実行が 0 回', deferred.runs.every((r) => r.rowsWhileTyping === 0));
const ratio = deferred.inp / bad.inp;
check('問題6: 自作の useDeferredValue 版の INP 中央値が Bad 版の 0.5 倍以下', ratio <= 0.5, `${ratio.toFixed(2)} 倍`);

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS08 練習問題の解答の検証に成功しました。');
