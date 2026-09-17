// 復習04「セッション20〜28の横断復習」で全問題が共有する部品。
//
// ここには「データ」と「金額の計算」しか置かない。判断のロジックは各問題側に書く。
// セッション18 の Result だけを import し、他のファイルは1つも import しない
// （依存の矢印を一方向にするため。セッション16 で学んだ方針）。

export { err, ok, tryCatchAsync } from '../session18/result';
export type { Result } from '../session18/result';

export type Role = 'user' | 'admin';

export type SessionUser = { id: number; email: string; name: string; role: Role };

/**
 * 一覧の表示と金額計算に必要な列だけを持つ商品の行。
 * この章では description と imageUrl を1度も使わないので省いている
 * （7フィールドすべてを持つ正式な型は Product。名前を分けて混同を避ける）。
 */
export type ProductRow = {
  id: number;
  name: string;
  price: number;
  stock: number;
  categoryId: number;
};

export type CategoryRow = { id: number; name: string; slug: string };

/** 金額計算に使う明細。product は上の ProductRow */
export type CartLine = { product: ProductRow; quantity: number };

export const CATEGORIES: readonly CategoryRow[] = [
  { id: 1, name: 'バス・ボディケア', slug: 'bath-body' },
  { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
  { id: 3, name: 'ファブリック', slug: 'fabric' },
];

export const PRODUCTS: readonly ProductRow[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

export const TAX_RATE = 0.1;
export const SHIPPING_FEE = 500;
export const FREE_SHIPPING_THRESHOLD = 3000;
export const MAX_CART_QUANTITY = 10;

/** 上の CATEGORIES の slug を、Zod の z.enum に渡せる形で並べたもの（順番も同じ） */
export const CATEGORY_SLUGS = ['bath-body', 'kitchen', 'fabric'] as const;

export const SORT_KEYS = ['price-asc', 'price-desc', 'name-asc'] as const;

export type SortKey = (typeof SORT_KEYS)[number];

export type DiscountRule = (subtotal: number) => number;

export type PaymentSummary = {
  subtotal: number;
  discountAmount: number;
  discountedTotal: number;
  tax: number;
  totalWithTax: number;
  shippingFee: number;
  payableAmount: number;
};

export function calcLineTotal(price: number, quantity: number): number {
  return price * quantity;
}

/** 送料は「税込商品合計」で判定する（税抜小計では判定しない） */
export function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

/** 本書共通の支払総額の計算手順。順序と丸めを変えない */
export function buildPaymentSummary(
  lines: readonly CartLine[],
  rule: DiscountRule = () => 0
): PaymentSummary {
  const subtotal = lines.reduce(
    (total, cartLine) => total + calcLineTotal(cartLine.product.price, cartLine.quantity),
    0
  );
  const discountAmount = Math.min(Math.floor(rule(subtotal)), subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = Math.floor(discountedTotal * TAX_RATE);
  const totalWithTax = discountedTotal + tax;
  const shippingFee = calcShippingFee(totalWithTax);

  return {
    subtotal,
    discountAmount,
    discountedTotal,
    tax,
    totalWithTax,
    shippingFee,
    payableAmount: totalWithTax + shippingFee,
  };
}

export function findProductRow(productId: number): ProductRow | undefined {
  return PRODUCTS.find((product) => product.id === productId);
}

export function findCategoryIdBySlug(slug: string): number | null {
  return CATEGORIES.find((category) => category.slug === slug)?.id ?? null;
}

/** マスタから明細を1行作る。無い商品を指定したら検証用データのバグなので例外を投げる */
export function cartLine(productId: number, quantity: number): CartLine {
  const product = findProductRow(productId);

  if (product === undefined) {
    throw new Error(`商品マスタが壊れています: id=${productId}`);
  }

  return { product, quantity };
}
