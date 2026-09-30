import { products, type Product } from './products';

/** 人気ランキングの集計にかかる時間（遅いデータの代わり） */
export const RANKING_DELAY_MS = 1500;

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 価格の高い順に 5 件。乱数を使わないので毎回同じ結果になる */
export async function loadRanking(): Promise<Product[]> {
  await sleep(RANKING_DELAY_MS);
  return [...products].sort((a, b) => b.price - a.price || a.id - b.id).slice(0, 5);
}
