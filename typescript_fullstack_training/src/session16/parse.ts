// 外から来た JSON を unknown で受け、型ガードで絞り込む。
import type { Product } from './types';

/** JSON.parse は any を返すので、unknown として受け直して外に出す */
export function parseJson(text: string): unknown {
  return JSON.parse(text);
}

/**
 * 値が Product の形をしているかを確かめるユーザー定義型ガード。
 * typeof null が 'object' を返すため、null を先に弾いている。
 */
export function isProduct(value: unknown): value is Product {
  if (typeof value !== 'object' || value === null) {
    return false;
  }

  return (
    'id' in value &&
    typeof value.id === 'number' &&
    'name' in value &&
    typeof value.name === 'string' &&
    'price' in value &&
    typeof value.price === 'number' &&
    'stock' in value &&
    typeof value.stock === 'number' &&
    'categoryId' in value &&
    typeof value.categoryId === 'number'
  );
}

/** JSON 文字列を Product に変換する。形が違えば undefined */
export function toProduct(text: string): Product | undefined {
  const value = parseJson(text);
  return isProduct(value) ? value : undefined;
}
