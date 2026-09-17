// カートの組み立て。値の import と型の import を書き分ける。
import { MAX_CART_QUANTITY } from './constants';
import { products } from './shop-data';
import type { CartItem, CartLine, Product } from './types';

/** id で商品を1件探す。見つからなければ undefined */
export function findProductById(id: number): Product | undefined {
  return products.find((product) => product.id === id);
}

/** DB 行の形（CartItem）を計算用の形（CartLine）に変換する。商品が見つからない明細は落とす */
export function toCartLines(items: readonly CartItem[]): CartLine[] {
  const lines: CartLine[] = [];

  for (const item of items) {
    const product = findProductById(item.productId);
    if (product === undefined) {
      continue; // 削除された商品を指す明細は無視する
    }
    lines.push({ product, quantity: item.quantity });
  }

  return lines;
}

/** 数量が1以上 MAX_CART_QUANTITY 以下か */
export function isWithinQuantityLimit(line: CartLine): boolean {
  return line.quantity >= 1 && line.quantity <= MAX_CART_QUANTITY;
}

/** 明細1行の表示用文字列 */
export function describeLine(line: CartLine): string {
  return `${line.product.name} × ${line.quantity}点 = ${line.product.price * line.quantity}円`;
}
