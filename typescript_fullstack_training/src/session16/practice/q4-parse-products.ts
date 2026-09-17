// 問題4：unknown で受けた JSON を型ガードで Product[] に絞り込む。
import { isProduct, parseJson } from '../parse';
import type { Product } from '../types';

/** 配列であり、かつ全要素が Product の形をしているか */
export function isProductArray(value: unknown): value is Product[] {
  if (!Array.isArray(value)) {
    return false;
  }

  const items: unknown[] = value;
  return items.every((item) => isProduct(item));
}

/** JSON 文字列を Product[] に変換する。1件でも形が違えば undefined */
export function toProducts(text: string): Product[] | undefined {
  const value = parseJson(text);
  return isProductArray(value) ? value : undefined;
}

/** 形が正しい要素だけを残す（部分的に壊れたデータから救えるものを拾う） */
export function collectValidProducts(text: string): Product[] {
  const value = parseJson(text);

  if (!Array.isArray(value)) {
    return [];
  }

  const items: unknown[] = value;
  return items.filter((item): item is Product => isProduct(item));
}

/** 正しい2件 */
export const VALID_JSON =
  '[{"id":1,"name":"ラベンダーの石けん","price":480,"stock":24,"categoryId":1},' +
  '{"id":3,"name":"マグカップ","price":2350,"stock":3,"categoryId":2}]';

/** 2件目に price / stock / categoryId が無い */
export const PARTIAL_JSON =
  '[{"id":1,"name":"ラベンダーの石けん","price":480,"stock":24,"categoryId":1},' +
  '{"id":4,"name":"リネンのふきん"}]';

/** 配列ではなくオブジェクト1件 */
export const OBJECT_JSON = '{"id":1,"name":"ラベンダーの石けん","price":480,"stock":24,"categoryId":1}';

function describeCount(products: Product[] | undefined): string {
  return products === undefined ? '(形が違います)' : `${products.length}件`;
}

export function formatParseResult(): string {
  const rescued = collectValidProducts(PARTIAL_JSON);

  return [
    `正しい配列: ${describeCount(toProducts(VALID_JSON))}`,
    `一部が壊れた配列: ${describeCount(toProducts(PARTIAL_JSON))}`,
    `配列でない JSON: ${describeCount(toProducts(OBJECT_JSON))}`,
    `壊れた要素を除いた件数: ${rescued.length}件`,
    `救えた商品: ${rescued.map((product) => product.name).join(' / ')}`,
  ].join('\n');
}
