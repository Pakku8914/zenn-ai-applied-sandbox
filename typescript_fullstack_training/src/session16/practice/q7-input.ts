// 問題7：外から来た JSON を unknown で受け、型ガードだけで OrderRequest に絞り込む。
import { parseJson } from '../parse';
import type { MemberRank } from '../types';

export type RequestItem = { productId: number; quantity: number };

export type OrderRequest = { rank: MemberRank; items: readonly RequestItem[] };

/** 会員ランクのリテラルかどうか */
function isMemberRank(value: unknown): value is MemberRank {
  return value === 'gold' || value === 'silver' || value === 'bronze' || value === 'none';
}

/** { productId: number, quantity: number } の形かどうか */
function isRequestItem(value: unknown): value is RequestItem {
  if (typeof value !== 'object' || value === null) {
    return false;
  }

  return (
    'productId' in value &&
    typeof value.productId === 'number' &&
    'quantity' in value &&
    typeof value.quantity === 'number'
  );
}

/** JSON 文字列を OrderRequest に変換する。形が違えば undefined */
export function toOrderRequest(text: string): OrderRequest | undefined {
  const value = parseJson(text);

  if (typeof value !== 'object' || value === null) {
    return undefined;
  }
  if (!('rank' in value) || !('items' in value)) {
    return undefined;
  }

  const rank: unknown = value.rank;
  const rawItems: unknown = value.items;

  if (!isMemberRank(rank) || !Array.isArray(rawItems)) {
    return undefined;
  }

  const rawList: unknown[] = rawItems;
  const items: RequestItem[] = [];

  for (const item of rawList) {
    if (!isRequestItem(item)) {
      return undefined; // 1件でも壊れていたら注文全体を受け付けない
    }
    items.push(item);
  }

  return { rank, items };
}

/** gold 会員の注文。productId=99 は存在しない商品 */
export const SAMPLE_ORDER_JSON =
  '{"rank":"gold","items":[{"productId":2,"quantity":1},' +
  '{"productId":5,"quantity":1},{"productId":99,"quantity":1}]}';

/** rank が MemberRank ではない（platinum は存在しない） */
export const INVALID_ORDER_JSON = '{"rank":"platinum","items":[]}';
