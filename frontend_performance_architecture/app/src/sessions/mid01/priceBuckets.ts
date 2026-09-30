import type { Product } from '../../data/products';

/** 価格帯の幅（円）。100〜9,999 円を 10 本の棒に分ける */
export const BUCKET_SIZE = 1_000;
export const BUCKET_COUNT = 10;

/** 価格帯ごとの商品数。2,000 件を 1 回なめるだけの軽い計算 */
export function priceBuckets(items: readonly Product[]): number[] {
  const counts = Array.from({ length: BUCKET_COUNT }, () => 0);
  for (const p of items) {
    const index = Math.min(Math.floor(p.price / BUCKET_SIZE), BUCKET_COUNT - 1);
    counts[index] = (counts[index] ?? 0) + 1;
  }
  return counts;
}
