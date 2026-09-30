import type { Product } from '../../../data/products';

export type CartSummary = { count: number; totalPrice: number };

/**
 * 練習問題3：カートの点数と合計金額は ids から毎回計算する（state に写さない）。
 * 見つからない商品は点数にも金額にも数えない（2つの値の根拠を1つにそろえる）。
 */
export function summarizeCart(ids: readonly number[], items: readonly Product[]): CartSummary {
  const byId = new Map(items.map((p) => [p.id, p]));
  let count = 0;
  let totalPrice = 0;
  for (const id of ids) {
    const product = byId.get(id);
    if (product === undefined) continue;
    count += 1;
    totalPrice += product.price;
  }
  return { count, totalPrice };
}
