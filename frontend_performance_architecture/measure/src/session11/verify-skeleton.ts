import { collectVitals, latestPerName, median, withPage } from '../vitals-client.ts';
import { TARGET, conditionsLabel, createChecker } from './helpers.ts';

/**
 * S11：一覧が 800ms 遅れて届く画面で、待っている間の表示と CLS の関係を比べる（各 5 回の中央値）。
 * 実行: docker compose exec measure node --experimental-strip-types src/session11/verify-skeleton.ts
 */
const RUNS = 5;
const PAGES = ['s11-skeleton-none', 's11-skeleton-mismatch', 's11-skeleton-fixed'] as const;
const { check, finish } = createChecker();

async function clsOnce(pageName: string): Promise<number> {
  return withPage(async (page) => {
    await collectVitals(page, `${TARGET}/pages/${pageName}/`);
    await page.waitForSelector('[data-list="loaded"]', { timeout: 10_000 });
    await page.waitForTimeout(500); // layout-shift の報告が web-vitals に届くのを待つ。入力はしない
    const vitals = latestPerName(await page.evaluate(() => window.__webVitals ?? []));
    return vitals.find((v) => v.name === 'CLS')?.value ?? 0; // ずれが一度もなければ CLS は報告されない＝0
  });
}

console.log(`計測条件: ${conditionsLabel()}（各${RUNS}回の中央値）`);
const medians: Record<string, number> = {};
for (const name of PAGES) {
  const values: number[] = [];
  for (let i = 0; i < RUNS; i += 1) values.push(await clsOnce(name));
  medians[name] = median(values);
  console.log(`${name}: CLS 中央値 ${medians[name]}（各回 ${values.join(' / ')}）`);
}
console.log('');

const none = medians['s11-skeleton-none'] ?? Number.NaN;
const mismatch = medians['s11-skeleton-mismatch'] ?? Number.NaN;
const fixed = medians['s11-skeleton-fixed'] ?? Number.NaN;

check('スケルトンなしの CLS 中央値が 0.1 以上（good の範囲を外れる）', none >= 0.1, String(none));
check('高さ違いのスケルトンでも CLS 中央値が 0.05 以上（ずれが残る）', mismatch >= 0.05, String(mismatch));
check('高さ違いのスケルトンは、スケルトンなしより CLS が小さい（ずれる距離が短い）', mismatch < none, `${mismatch} < ${none}`);
check('高さ一致のスケルトンの CLS 中央値が 0.1 未満（good）', fixed < 0.1, String(fixed));
check(
  '高さ一致のスケルトンの CLS 中央値が、高さ違いの 0.2 倍以下',
  fixed <= mismatch * 0.2,
  `${(fixed / mismatch).toFixed(2)} 倍`,
);

finish('S11 のスケルトンと CLS');
