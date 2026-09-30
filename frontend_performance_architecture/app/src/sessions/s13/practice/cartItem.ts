import { isRecord, type ParseResult } from '../catalog/productGuard';

export type CartItem = { productId: number; quantity: number };

export const MAX_QUANTITY = 99;

/** 1件ぶんの検証。localStorage の中身は利用者が書き換えられるので、信用せずに確かめる */
export function parseCartItem(value: unknown): ParseResult<CartItem> {
  if (!isRecord(value)) return { ok: false, reason: 'オブジェクトではありません' };
  const { productId, quantity } = value;
  if (typeof productId !== 'number' || !Number.isInteger(productId) || productId < 1) {
    return { ok: false, reason: 'productId は 1 以上の整数にしてください' };
  }
  if (typeof quantity !== 'number' || !Number.isInteger(quantity) || quantity < 1 || quantity > MAX_QUANTITY) {
    return { ok: false, reason: `quantity は 1〜${MAX_QUANTITY} の整数にしてください` };
  }
  return { ok: true, value: { productId, quantity } };
}

/** 保存された文字列からカートを復元する。壊れた JSON は空、形の違う要素は読み飛ばす */
export function readCart(raw: string | null): CartItem[] {
  if (raw === null) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const list: readonly unknown[] = parsed;

  const items: CartItem[] = [];
  for (const entry of list) {
    const result = parseCartItem(entry);
    if (result.ok) items.push(result.value);
  }
  return items;
}
