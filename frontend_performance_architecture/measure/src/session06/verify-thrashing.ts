import { median, withPage } from '../vitals-client.ts';
import { conditionsLabel, createChecker, layoutCounter, ms1, openLab } from './lab.ts';

/**
 * S06：レイアウトスラッシング（Bad）と読み書きの分離（Good）を、レイアウト回数と所要時間で比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session06/verify-thrashing.ts
 * レイアウト回数は行数で決まるので下限・上限で、時間は比率で判定する。
 */
const RUNS = 5;
const ROWS = 2_000;
const { check, finish } = createChecker();

type Sample = { ms: number; layouts: number; barWidthSum: number; narrowCount: number; rows: number };

const samples = await withPage(async (page) => {
  await openLab(page);
  const layouts = await layoutCounter(page);

  const run = async (kind: 'drawBars' | 'markNarrow', mode: string): Promise<Sample> => {
    const before = await layouts();
    const ms = await page.evaluate(
      ([k, m]) => (k === 'drawBars' ? window.__s06Lab!.drawBars(m as 'thrashing') : window.__s06Lab!.markNarrow(m as 'thrashing')),
      [kind, mode] as const,
    );
    const after = await layouts();
    const snap = await page.evaluate(() => window.__s06Lab!.snapshot());
    return { ms, layouts: after - before, ...snap };
  };

  const result: Record<string, Sample[]> = {
    'drawBars:thrashing': [],
    'drawBars:batched': [],
    'markNarrow:thrashing': [],
    'markNarrow:phased': [],
  };
  // Bad と Good を交互に実行し、時間の経過による揺れが片方に偏らないようにする
  for (let i = 0; i < RUNS; i += 1) {
    for (const key of Object.keys(result)) {
      const [kind, mode] = key.split(':') as ['drawBars' | 'markNarrow', string];
      result[key]!.push(await run(kind, mode));
    }
  }
  return result;
});

const summary = Object.entries(samples).map(([key, list]) => ({
  処理: key,
  レイアウト回数: median(list.map((s) => s.layouts)),
  '所要時間（中央値）': ms1(median(list.map((s) => s.ms))),
  行数: list[0]?.rows ?? 0,
}));

console.log(`計測条件: ${conditionsLabel()} / ${ROWS.toLocaleString('en-US')} 行 / 各${RUNS}回の中央値`);
console.table(summary);

const get = (key: string): Sample[] => samples[key] ?? [];
const medMs = (key: string): number => median(get(key).map((s) => s.ms));
const medLayouts = (key: string): number => median(get(key).map((s) => s.layouts));

check(`一覧が ${ROWS.toLocaleString('en-US')} 行ある`, get('drawBars:batched')[0]?.rows === ROWS, `${get('drawBars:batched')[0]?.rows ?? 0} 行`);

// 結果が同じであること（速くても描いた内容が違えば改善ではない）
const widthSums = new Set([...get('drawBars:thrashing'), ...get('drawBars:batched')].map((s) => s.barWidthSum));
check('Bad と Good でバーの幅の合計が一致する', widthSums.size === 1, `${[...widthSums].join(' / ')}px`);
const narrowCounts = new Set([...get('markNarrow:thrashing'), ...get('markNarrow:phased')].map((s) => s.narrowCount));
check('Bad と Good で細いバーの数が一致する', narrowCounts.size === 1, `${[...narrowCounts].join(' / ')} 本`);

check('drawBars の Bad はレイアウトが行数ぶん起きる（2,000 回以上）', medLayouts('drawBars:thrashing') >= ROWS, `${medLayouts('drawBars:thrashing')} 回`);
check('drawBars の Good はレイアウトが 3 回以下', medLayouts('drawBars:batched') <= 3, `${medLayouts('drawBars:batched')} 回`);
check('markNarrow の Bad はレイアウトが行数ぶん起きる（2,000 回以上）', medLayouts('markNarrow:thrashing') >= ROWS, `${medLayouts('markNarrow:thrashing')} 回`);
check('markNarrow の Good はレイアウトが 3 回以下', medLayouts('markNarrow:phased') <= 3, `${medLayouts('markNarrow:phased')} 回`);

const drawRatio = medMs('drawBars:batched') / medMs('drawBars:thrashing');
check('drawBars の Good の所要時間が Bad の 0.5 倍以下', drawRatio <= 0.5, `${drawRatio.toFixed(2)} 倍`);
const markRatio = medMs('markNarrow:phased') / medMs('markNarrow:thrashing');
check('markNarrow の Good の所要時間が Bad の 0.5 倍以下', markRatio <= 0.5, `${markRatio.toFixed(2)} 倍`);

finish('S06 のレイアウトスラッシング');
