import { median, withPage } from '../vitals-client.ts';
import { conditionsLabel, createChecker, ms1, openLab } from './lab.ts';

/**
 * S06：contain の効果。1行の在庫表示を書き換えては読む操作を、contain なし／あり（strict）で比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session06/verify-contain.ts
 */
const RUNS = 5;
const TIMES = 300;
const { check, finish } = createChecker();

const result = await withPage(async (page) => {
  await openLab(page);
  const plain: number[] = [];
  const contained: number[] = [];
  const applied = new Set<string>();
  for (let i = 0; i < RUNS; i += 1) {
    const a = await page.evaluate((n) => window.__s06Lab!.editStock(false, n), TIMES);
    const b = await page.evaluate((n) => window.__s06Lab!.editStock(true, n), TIMES);
    plain.push(a.ms);
    contained.push(b.ms);
    applied.add(`${a.contain}→${b.contain}`);
  }
  return { plain: median(plain), contained: median(contained), applied: [...applied] };
});

console.log(`計測条件: ${conditionsLabel()} / 書き換え ${TIMES} 回 / 各${RUNS}回の中央値`);
console.table([
  { 行のスタイル: 'contain なし', 所要時間: ms1(result.plain) },
  { 行のスタイル: 'contain: strict', 所要時間: ms1(result.contained) },
]);

check('contain の付け外しが効いている（none → strict）', result.applied.length === 1 && result.applied[0] === 'none→strict', result.applied.join(', '));
const ratio = result.contained / result.plain;
check('contain: strict の所要時間が contain なしの 0.8 倍以下', ratio <= 0.8, `${ratio.toFixed(2)} 倍`);

finish('S06 の contain');
