// ミニ雑貨ショップの商品・カテゴリのマスタデータ。
// データベースはセッション23で導入する。それまではこの静的な配列を「仮のデータベース」として使う。
// 中身は sandbox/fixtures の products.json / categories.json と同じ。

/** 商品。フィールドはセッション11で決めた7つ（データベースを使い始めても同じ形） */
export type Product = {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

/** カテゴリ。slug は URL に出すための短い英字の名前 */
export type Category = {
  id: number;
  name: string;
  slug: string;
};

export const CATEGORIES: readonly Category[] = [
  { id: 1, name: 'バス・ボディケア', slug: 'bath-body' },
  { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
  { id: 3, name: 'ファブリック', slug: 'fabric' },
];

export const PRODUCTS: readonly Product[] = [
  {
    id: 1,
    name: 'ラベンダーの石けん',
    price: 480,
    stock: 24,
    description: 'ラベンダーの精油を練り込んだ手作りの石けんです。',
    imageUrl: '/images/products/lavender-soap.png',
    categoryId: 1,
  },
  {
    id: 2,
    name: 'ハンドクリーム',
    price: 1800,
    stock: 12,
    description: 'べたつかない使用感の保湿ハンドクリームです。',
    imageUrl: '/images/products/hand-cream.png',
    categoryId: 1,
  },
  {
    id: 3,
    name: 'マグカップ',
    price: 2350,
    stock: 3,
    description: '厚みのある陶器で、冷めにくいマグカップです。',
    imageUrl: '/images/products/mug.png',
    categoryId: 2,
  },
  {
    id: 4,
    name: 'リネンのふきん',
    price: 990,
    stock: 0,
    description: '洗うほどやわらかくなるリネン100%のふきんです。',
    imageUrl: '/images/products/linen-cloth.png',
    categoryId: 3,
  },
  {
    id: 5,
    name: 'コットンのトートバッグ',
    price: 2800,
    stock: 5,
    description: 'A4サイズが入る、しっかりした厚手のトートバッグです。',
    imageUrl: '/images/products/tote-bag.png',
    categoryId: 3,
  },
];

/** id で商品を1件探す。無ければ undefined */
export function findProductById(id: number): Product | undefined {
  return PRODUCTS.find((product) => product.id === id);
}

/** id でカテゴリを1件探す */
export function findCategoryById(id: number): Category | undefined {
  return CATEGORIES.find((category) => category.id === id);
}

/** slug（URL に出す名前）でカテゴリを1件探す */
export function findCategoryBySlug(slug: string): Category | undefined {
  return CATEGORIES.find((category) => category.slug === slug);
}
