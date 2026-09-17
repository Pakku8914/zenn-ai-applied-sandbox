// 集計するモジュール。ここも純粋関数だけ。
// 受け取るのは「変換済みの配列」と「カテゴリの表示順」だけで、
// Category 型そのものは受け取らない（集計に必要なのは名前の並びだけだから）。

import type { CatalogItem, CategorySummary, ProductReport } from './types';

/** カテゴリごとに件数・在庫数・在庫金額を出す。商品が0件のカテゴリも行として残す */
export function summarizeByCategory(
  items: readonly CatalogItem[],
  categoryNames: readonly string[]
): CategorySummary[] {
  return categoryNames.map((categoryName) => {
    const owned = items.filter((item) => item.categoryName === categoryName);

    return {
      categoryName,
      count: owned.length,
      stockQuantity: owned.reduce((total, item) => total + item.stock, 0),
      stockValue: owned.reduce((total, item) => total + item.price * item.stock, 0),
    };
  });
}

/** 平均単価。0件のときに NaN を返さないよう、先に件数を見る */
export function calcAveragePrice(items: readonly CatalogItem[]): number {
  if (items.length === 0) {
    return 0;
  }
  const total = items.reduce((sum, item) => sum + item.price, 0);
  // 金額は整数（円）で扱う方針なので、小数点以下は切り捨てる
  return Math.floor(total / items.length);
}

/** レポートに出す数値を1つのオブジェクトにまとめる */
export function buildReport(
  items: readonly CatalogItem[],
  categoryNames: readonly string[]
): ProductReport {
  return {
    rows: summarizeByCategory(items, categoryNames),
    totalCount: items.length,
    // 合計はカテゴリ別の行から足すのではなく、元の配列から直接求める。
    // 行の合計と全体の合計が一致することが、変換が正しかったことの確認にもなる。
    totalStockQuantity: items.reduce((total, item) => total + item.stock, 0),
    totalStockValue: items.reduce((total, item) => total + item.price * item.stock, 0),
    averagePrice: calcAveragePrice(items),
    soldOutNames: items.filter((item) => item.stock <= 0).map((item) => item.name),
  };
}
