import { measureMedian, median } from '../vitals-client.ts';

/**
 * S03：同じ条件でも値が揺れることを確かめ、中央値で代表値を採る。
 * 各回の値は環境で変わるので、判定は「全回で取れたか」「中央値が範囲内か」で行う。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const RUNS = 5;
const failures: string[] = [];
function check(name: string, ok: boolean, detail: string): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name} — ${detail}`);
  if (!ok) failures.push(name);
}

// 1. 中央値と平均の違い（決定的な計算）。本書の検証で CLS は 0 と 0.509 の両方が出た
const clsSample = [0, 0, 0.509];
const clsMean = clsSample.reduce((a, b) => a + b, 0) / clsSample.length;
check('CLS [0, 0, 0.509] の中央値は 0（good）', median(clsSample) === 0, `中央値 ${median(clsSample)}`);
check('同じ値の平均は 0.1 を超える（good 判定から外れる）', clsMean > 0.1, `平均 ${clsMean.toFixed(3)}`);
console.log('');

// 2. 実測：毎回新しいブラウザで RUNS 回計測する（LCP を取ってから「商品1」を入力）
const result = await measureMedian(TARGET, {
  runs: RUNS,
  input: { selector: '#keyword', value: '商品1' },
});

console.log(`計測対象: ${TARGET}（CPU 4x / 1500kbps / RTT 40ms / 本番ビルド / ${RUNS} 回）`);
for (const name of ['LCP', 'INP', 'CLS', 'TTFB']) {
  const values = result.runs.flatMap((run) => run.vitals.filter((v) => v.name === name).map((v) => v.value));
  const unit = name === 'CLS' ? '' : 'ms';
  console.log(
    `${name.padEnd(4)}  各回: ${values.map((v) => `${v}${unit}`).join(' / ')}  → 中央値 ${result.median[name]}${unit}`,
  );
  if (name === 'CLS') continue; // CLS は移動が無い回では値が変化しないことがあるため、回数は問わない

  check(`${name} が全 ${RUNS} 回で取れている`, values.length === RUNS, `${values.length} 回`);
  if (values.length === 0) continue;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const m = result.median[name] ?? Number.NaN;
  check(`${name} の中央値が最小〜最大の範囲にある`, lo <= m && m <= hi, `${lo} ≦ ${m} ≦ ${hi}`);
  check(`${name} の中央値が median() と一致する`, m === median(values), `${m}`);
}

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS03 中央値の検証に成功しました。');
