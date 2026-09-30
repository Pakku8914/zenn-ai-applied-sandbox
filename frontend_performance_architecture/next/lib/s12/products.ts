export type Product = {
  id: number;
  name: string;
  price: number;
  category: string;
};

const CATEGORIES = ['文具', '書籍', '雑貨', '食品'] as const;

/**
 * SPA 側（app/src/data/products.ts）と同じ生成式の 2,000 件。
 * next/ から app/ は import できないため複製している。件数と式は変えない。
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

/** 商品名にキーワードを含むものだけを返す（SPA 版の ProductList と同じ条件） */
export function filterProducts(keyword: string): Product[] {
  return products.filter((p) => p.name.includes(keyword));
}
