// セッション19「テストとコード品質」で使うテスト用のデータ。
// 商品マスタ（セッション16の shop-data）から必要な形を組み立てる。
// 同じリテラルをテストのあちこちに散らさないよう、ここに1か所だけ置く。

import { products } from '../session16/shop-data';
import type { CartLine, Product } from '../session16/types';
import type { CatalogItem } from '../session17/catalog';

/** id で1件取り出す。見つからなければ即座に失敗させる（テストデータの取り違えを早く見つけるため） */
export function requireById<T extends { id: number }>(
  items: readonly T[],
  id: number,
  label = '要素'
): T {
  const found = items.find((item) => item.id === id);

  if (found === undefined) {
    throw new Error(`テスト用の${label}が見つかりません: id=${id}`);
  }
  return found;
}

/** 商品マスタから1件取り出す */
export function requireProduct(id: number): Product {
  return requireById(products, id, '商品');
}

/** カテゴリ名（fixtures/categories.json と同じ値） */
const CATEGORY_NAMES: Record<number, string> = {
  1: 'バス・ボディケア',
  2: 'キッチン雑貨',
  3: 'ファブリック',
};

/**
 * セッション17の CatalogItem 形式のテストデータ。
 * fixture を非同期に読まずに済むよう、商品マスタから同期で組み立てている。
 */
export const catalogItems: readonly CatalogItem[] = products.map((product) => ({
  id: product.id,
  name: product.name,
  price: product.price,
  stock: product.stock,
  categoryName: CATEGORY_NAMES[product.categoryId] ?? '（カテゴリ未設定）',
}));

/** カタログから1件取り出す */
export function requireCatalogItem(id: number): CatalogItem {
  return requireById(catalogItems, id, 'カタログ項目');
}

/** コットンのトートバッグ1点（税抜2800円）。送料判定を税抜／税込のどちらでするかで結果が変わる */
export const toteBagCart: readonly CartLine[] = [{ product: requireProduct(5), quantity: 1 }];

/** ラベンダーの石けん2点 + マグカップ1点（税抜3310円） */
export const mixedCart: readonly CartLine[] = [
  { product: requireProduct(1), quantity: 2 },
  { product: requireProduct(3), quantity: 1 },
];

/** ラベンダーの石けん3点（税抜1440円）。送料がかかるカート */
export const soapCart: readonly CartLine[] = [{ product: requireProduct(1), quantity: 3 }];
