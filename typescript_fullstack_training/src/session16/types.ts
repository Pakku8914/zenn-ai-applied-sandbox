// セッション16「モジュール・tsconfig・null 安全」で使う型の定義。
// このファイルは値を1つも持たず、誰も import しない（依存の矢印を一方向にするため）。
// 商品マスタのうち、この章で使わない description と imageUrl は省いている。

export type Product = {
  id: number;
  name: string;
  price: number;
  stock: number;
  categoryId: number;
};

export type CartItem = {
  id: number;
  userId: number;
  productId: number;
  quantity: number;
};

/** 金額計算・表示に使う最小限の明細（DB 行の CartItem とは別の形） */
export type CartLine = { product: Product; quantity: number };

export type MemberRank = 'gold' | 'silver' | 'bronze' | 'none';

/** 小計を受け取って割引額を返す関数（セッション6で決めた形） */
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
