import type { Product } from '../../data/products';

const CATEGORIES = ['文具', '書籍', '雑貨', '食品'] as const;

/**
 * 出発点（src/data/products.ts）と同じ生成式で、件数だけを変えた商品データを作る。
 * makeProducts(2000) は出発点の products と完全に一致する（s08.test.tsx で確認）。
 */
export function makeProducts(count: number): Product[] {
  return Array.from({ length: count }, (_, index) => {
    const i = index + 1;
    return {
      id: i,
      name: `商品${i}`,
      price: 100 + ((i * 37) % 9900),
      category: CATEGORIES[i % CATEGORIES.length] ?? '文具',
    };
  });
}
