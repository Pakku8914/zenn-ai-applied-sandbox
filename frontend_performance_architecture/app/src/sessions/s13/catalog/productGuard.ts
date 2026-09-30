import type { Product } from '../../../data/products';

/** 検証の結果。成功なら値、失敗なら理由を持つ（判別可能ユニオン） */
export type ParseResult<T> = { ok: true; value: T } | { ok: false; reason: string };

type FieldType = 'number' | 'string';

/**
 * Product の各項目の型。satisfies で「Product のキーをすべて持つこと」を確かめる。
 * Product に項目が増えたら、ここが型エラーになって検証の書き足し忘れに気づける。
 */
const PRODUCT_SHAPE = {
  id: 'number',
  name: 'string',
  price: 'number',
  category: 'string',
} satisfies Record<keyof Product, FieldType>;

const PRODUCT_KEYS = Object.keys(PRODUCT_SHAPE) as (keyof Product)[];

/** 外から来る配列の上限。巨大な応答で画面が固まらないようにする */
export const MAX_PRODUCTS = 10_000;

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasType(field: unknown, type: FieldType): boolean {
  return type === 'number' ? typeof field === 'number' && Number.isFinite(field) : typeof field === 'string';
}

/** 型ガード。true を返したときだけ、TypeScript は value を Product として扱う */
export function isProduct(value: unknown): value is Product {
  if (!isRecord(value)) return false;
  const record = value;
  return PRODUCT_KEYS.every((key) => hasType(record[key], PRODUCT_SHAPE[key]));
}

/**
 * 外から来た値（通信の応答・保存データ）を商品の一覧として受け取る。
 * 形が違えば例外ではなく理由付きの失敗を返す。余分な項目は写さずに落とす。
 */
export function parseProducts(value: unknown): ParseResult<Product[]> {
  if (!Array.isArray(value)) return { ok: false, reason: '商品の一覧が配列ではありません' };
  const list: readonly unknown[] = value;
  if (list.length > MAX_PRODUCTS) return { ok: false, reason: `商品が多すぎます（上限 ${MAX_PRODUCTS} 件）` };

  const items: Product[] = [];
  for (const [index, item] of list.entries()) {
    if (!isProduct(item)) return { ok: false, reason: `${index} 番目の要素が商品の形をしていません` };
    items.push({ id: item.id, name: item.name, price: item.price, category: item.category });
  }
  return { ok: true, value: items };
}
