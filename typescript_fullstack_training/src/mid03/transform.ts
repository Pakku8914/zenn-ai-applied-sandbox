// 検証済みのデータを「レポートに使える形」に変えるモジュール。
// 非同期処理も入出力もここには無い。純粋関数だけなのでテストが書きやすい。

import { collectResults, err, ok } from '../session18/result';
import type { Result } from '../session18/result';
import type { CatalogItem, Category, Product, TransformError } from './types';

/** カテゴリIDから名前を引ける Map を作る（毎回 find すると件数の2乗に比例して遅くなる） */
export function buildCategoryIndex(categories: readonly Category[]): Map<number, string> {
  return new Map(categories.map((category): [number, string] => [category.id, category.name]));
}

/**
 * 商品1件にカテゴリ名を紐づける。
 * セッション17 の buildCatalog は未知のカテゴリを「（カテゴリ未設定）」で埋めていたが、
 * この CLI ではデータの不整合を知らせたいので、失敗として返す。
 */
export function toCatalogItem(
  product: Product,
  categoryNameById: Map<number, string>
): Result<CatalogItem, TransformError> {
  const categoryName = categoryNameById.get(product.categoryId);
  if (categoryName === undefined) {
    return err<TransformError>({
      kind: 'unknown_category',
      productName: product.name,
      categoryId: product.categoryId,
    });
  }

  return ok({
    id: product.id,
    name: product.name,
    price: product.price,
    stock: product.stock,
    categoryName,
  });
}

/** 全件を変換する。1件でも失敗したら、失敗を全部集めて返す */
export function toCatalogItems(
  products: readonly Product[],
  categories: readonly Category[]
): Result<CatalogItem[], TransformError[]> {
  const categoryNameById = buildCategoryIndex(categories);
  return collectResults(products.map((product) => toCatalogItem(product, categoryNameById)));
}
