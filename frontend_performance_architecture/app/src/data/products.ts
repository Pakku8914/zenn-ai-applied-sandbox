export type Product = {
  id: number;
  name: string;
  price: number;
  category: string;
};

const CATEGORIES = ['文具', '書籍', '雑貨', '食品'] as const;

/**
 * 2,000 件の商品データを決定的に生成する（乱数を使わないので毎回同じ）。
 * 実測値を本文に載せるため、件数と生成式は章をまたいで変えない。
 */
export const products: Product[] = Array.from({ length: 2000 }, (_, index) => {
  const i = index + 1;
  return {
    id: i,
    name: `商品${i}`,
    price: 100 + ((i * 37) % 9900),
    category: CATEGORIES[i % CATEGORIES.length] ?? '文具',
  };
});
