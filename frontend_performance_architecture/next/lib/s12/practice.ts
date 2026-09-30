import { sleep } from './ranking';

/** 練習問題4：速いデータ（在庫）と遅いデータ（レビュー） */
export const STOCK_DELAY_MS = 600;
export const REVIEW_DELAY_MS = 1800;

export async function loadStock(productId: number): Promise<number> {
  await sleep(STOCK_DELAY_MS);
  return (productId * 7) % 50;
}

export async function loadReviews(): Promise<string[]> {
  await sleep(REVIEW_DELAY_MS);
  return ['書き心地がよい', '値段のわりに丈夫', '色の種類がもっと欲しい'];
}
