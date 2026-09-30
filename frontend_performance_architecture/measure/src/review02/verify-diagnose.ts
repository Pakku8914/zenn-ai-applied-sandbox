import { CONDITIONS } from '../vitals-client.ts';
import { CAUSE_LABEL, INP_GOOD_MS, LAYOUTS_PER_INPUT, diagnose, type Cause, type Evidence } from './diagnose.ts';
import { KEYWORD, RUNS, evidenceRows, ms, n, observeSubjects } from './evidence.ts';

/**
 * 横断復習②：diagnose() の規則を固定値で確かめてから、4ページを計測して原因の判定が期待どおりかを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/review02/verify-diagnose.ts
 * 行の実行回数・行数は完全一致、レイアウト回数は下限・上限、INP は good の境界との大小で判定する。
 */
const failures: string[] = [];
function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

// ---- 1. 規則の検査（ブラウザを使わない。数値は練習用の架空の値） ----
const fixtures: { label: string; e: Evidence; cause: Cause; worthFixing: boolean }[] = [
  { label: '処理時間だけが長い', e: { inputs: 3, inpMs: 272, rowRenders: 0, layouts: 6 }, cause: 'long-task', worthFixing: true },
  { label: '行が大量に実行される', e: { inputs: 3, inpMs: 250, rowRenders: 51_111, layouts: 6 }, cause: 'rerender', worthFixing: true },
  { label: 'レイアウトが大量に起きる', e: { inputs: 3, inpMs: 230, rowRenders: 0, layouts: 10_222 }, cause: 'layout', worthFixing: true },
  { label: '両方あればレイアウトを先に疑う', e: { inputs: 3, inpMs: 300, rowRenders: 51_111, layouts: 10_222 }, cause: 'layout', worthFixing: true },
  { label: '行は多いが INP は good', e: { inputs: 3, inpMs: 64, rowRenders: 5_111, layouts: 6 }, cause: 'rerender', worthFixing: false },
  { label: 'INP が報告されない（40ms 未満）', e: { inputs: 3, inpMs: null, rowRenders: 0, layouts: 0 }, cause: 'long-task', worthFixing: false },
  { label: 'good の境界ちょうど', e: { inputs: 1, inpMs: INP_GOOD_MS, rowRenders: 0, layouts: 0 }, cause: 'long-task', worthFixing: true },
];
for (const f of fixtures) {
  const v = diagnose(f.e);
  check(`規則: ${f.label}`, v.cause === f.cause && v.worthFixing === f.worthFixing, `${v.cause} / 直す=${v.worthFixing}`);
}
let threw = false;
try {
  diagnose({ inputs: 0, inpMs: 100, rowRenders: 0, layouts: 0 });
} catch {
  threw = true;
}
check('規則: 入力 0 回は例外にする（0 で割らない）', threw);
console.log('');

// ---- 2. 実際のページで証拠を集めて判定する ----
const { cpuThrottlingRate, network } = CONDITIONS;
console.log(
  `計測条件: CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド（各${RUNS}回の中央値）`,
);
console.log(`入力: #keyword に「${KEYWORD}」（pressSequentially）`);
const summaries = await observeSubjects();
console.table(evidenceRows(summaries));

type Expect = { rowRenders: number; minLayouts?: number; cause: Cause; worthFixing: boolean };
const EXPECT: Record<string, Expect> = {
  // 「商」「商品」で全件、「商品1」で 11,111 件が実行される（S08 と同じ数え方）
  'r02-freeze-a': { rowRenders: 51_111, cause: 'rerender', worthFixing: true },
  'r02-freeze-b': { rowRenders: 0, cause: 'long-task', worthFixing: true },
  // 1行につき2列 × (2,000 + 2,000 + 1,111) 行 = 10,222 回の強制同期レイアウト
  'r02-freeze-c': { rowRenders: 0, minLayouts: 10_000, cause: 'layout', worthFixing: true },
  's08-bad-2k': { rowRenders: 5_111, cause: 'rerender', worthFixing: false },
};

for (const { subject, median: m, runs } of summaries) {
  const want = EXPECT[subject.name];
  if (!want) throw new Error(`期待値がありません: ${subject.name}`);
  check(
    `${subject.name}: 入力中の行の実行が ${n(want.rowRenders)} 回（${RUNS}回すべて）`,
    runs.every((r) => r.rowRenders === want.rowRenders),
    runs.map((r) => n(r.rowRenders)).join(' / '),
  );
  check(
    `${subject.name}: 入力後の行数が ${n(subject.matched)}`,
    runs.every((r) => r.liAfter === subject.matched),
  );
  const layoutsOk =
    want.minLayouts !== undefined
      ? runs.every((r) => r.layouts >= want.minLayouts!)
      : runs.every((r) => r.layouts < LAYOUTS_PER_INPUT * r.inputs);
  check(
    `${subject.name}: レイアウト回数が ${want.minLayouts !== undefined ? `${n(want.minLayouts)} 回以上` : `1入力あたり ${LAYOUTS_PER_INPUT} 回未満`}`,
    layoutsOk,
    runs.map((r) => n(r.layouts)).join(' / '),
  );
  const v = diagnose(m);
  check(
    `${subject.name}: 判定が「${CAUSE_LABEL[want.cause]}」・${want.worthFixing ? '直す' : '今は直さない'}`,
    v.cause === want.cause && v.worthFixing === want.worthFixing,
    `${CAUSE_LABEL[v.cause]} / INP ${ms(m.inpMs)}`,
  );
}

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\n横断復習②の原因の切り分けの検証に成功しました。');
