// 問題2：窓口ファイル経由で値と型を取り込む側。
import { findProductById, products } from './q2-catalog';
import type { Product } from './q2-catalog';

/** export していないので、このファイルの中だけで使える */
function formatProduct(product: Product): string {
  return `${product.name}（${product.price}円 / 在庫${product.stock}点）`;
}

export function describeCatalog(): string {
  const first = products[0]; // Product | undefined
  const mug = findProductById(3);
  const missing = findProductById(99);

  return [
    `取り扱い商品: ${products.length}件`,
    `先頭: ${first === undefined ? '(なし)' : formatProduct(first)}`,
    `id=3: ${mug === undefined ? '(なし)' : formatProduct(mug)}`,
    `id=99: ${missing === undefined ? '(なし)' : formatProduct(missing)}`,
  ].join('\n');
}
