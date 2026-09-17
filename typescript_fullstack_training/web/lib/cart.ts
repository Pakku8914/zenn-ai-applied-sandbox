// カートの状態を更新する純粋関数。React には依存しない。
// useState に渡す「次の状態を作る関数」の中身をここに集めてある。
// 同じロジックの検証は src/session22/verify.ts にある（src からは web を import できないため）。

import type { Product } from '@/lib/products';

/** 1明細あたりの数量の上限（セッション15で決めた値） */
export const MAX_CART_QUANTITY = 10;

/** 金額計算・表示に使う最小限のカート明細（セッション12で決めた形） */
export type CartLine = {
  product: Product;
  quantity: number;
};

/** 数量を 1〜MAX_CART_QUANTITY の整数に収める */
export function clampQuantity(quantity: number): number {
  const rounded = Math.floor(quantity);

  return Math.min(Math.max(rounded, 1), MAX_CART_QUANTITY);
}

/**
 * 明細を追加した新しい配列を返す。
 * 同じ商品がすでにあれば明細を増やさず、その明細の数量を足す（1商品につき1明細）。
 */
export function addLine(
  lines: readonly CartLine[],
  product: Product,
  quantity: number = 1
): CartLine[] {
  const exists = lines.some((line) => line.product.id === product.id);

  if (!exists) {
    return [...lines, { product, quantity: clampQuantity(quantity) }];
  }

  return lines.map((line) =>
    line.product.id === product.id
      ? { ...line, quantity: clampQuantity(line.quantity + quantity) }
      : line
  );
}

/** 指定した商品の数量を差し替えた新しい配列を返す */
export function changeQuantity(
  lines: readonly CartLine[],
  productId: number,
  quantity: number
): CartLine[] {
  return lines.map((line) =>
    line.product.id === productId ? { ...line, quantity: clampQuantity(quantity) } : line
  );
}

/** 指定した商品の明細を取り除いた新しい配列を返す */
export function removeLine(lines: readonly CartLine[], productId: number): CartLine[] {
  return lines.filter((line) => line.product.id !== productId);
}

/** カートに入っている合計点数 */
export function calcTotalQuantity(lines: readonly CartLine[]): number {
  return lines.reduce((total, line) => total + line.quantity, 0);
}

/** この明細はもう増やせないか（練習問題6。画面に 10 を直接書かないための関数） */
export function isAtMaxQuantity(line: CartLine): boolean {
  return line.quantity >= MAX_CART_QUANTITY;
}

/** 数量の入力欄から届いた文字列を数量として解釈する。解釈できなければ null */
export function parseQuantity(raw: string): number | null {
  const trimmed = raw.trim();

  if (!/^[1-9][0-9]*$/.test(trimmed)) {
    return null;
  }

  const quantity = Number(trimmed);

  return quantity <= MAX_CART_QUANTITY ? quantity : null;
}

/** 選択肢に出す数量の一覧。在庫と上限の小さいほうまで */
export function buildQuantityOptions(stock: number): number[] {
  const max = Math.min(Math.max(stock, 1), MAX_CART_QUANTITY);

  return Array.from({ length: max }, (_, index) => index + 1);
}

/** ブラウザに保存するときのキー */
export const CART_STORAGE_KEY = 'mini-zakka-cart';

/** 保存する形。商品の全フィールドではなく id と数量だけを保存する */
export type StoredCartLine = {
  productId: number;
  quantity: number;
};

export function toStoredCart(lines: readonly CartLine[]): StoredCartLine[] {
  return lines.map((line) => ({ productId: line.product.id, quantity: line.quantity }));
}

/** 保存された文字列は「外から来た値」なので unknown として受け、型ガードで確かめる */
function isStoredCartLine(value: unknown): value is StoredCartLine {
  return (
    typeof value === 'object' &&
    value !== null &&
    'productId' in value &&
    typeof value.productId === 'number' &&
    'quantity' in value &&
    typeof value.quantity === 'number'
  );
}

function safeJsonParse(raw: string | null): unknown {
  if (raw === null) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * 保存された文字列からカートを復元する。
 * 壊れていた・知らない商品 id が入っていた場合は、その明細を静かに捨てる。
 */
export function parseStoredCart(raw: string | null, products: readonly Product[]): CartLine[] {
  const parsed = safeJsonParse(raw);

  if (!Array.isArray(parsed)) {
    return [];
  }

  return parsed.filter(isStoredCartLine).flatMap((stored): CartLine[] => {
    const product = products.find((candidate) => candidate.id === stored.productId);

    return product === undefined ? [] : [{ product, quantity: clampQuantity(stored.quantity) }];
  });
}
