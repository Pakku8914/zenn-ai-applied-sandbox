// 問題1：在庫レポートのロジック。console.log は持たない（呼ばれる側に徹する）。
import { LOW_STOCK_THRESHOLD } from './q1-constants';
import type { StockItem, StockReport } from './q1-types';

/** 在庫金額の合計（price * stock の総和） */
export function calcStockValue(items: readonly StockItem[]): number {
  return items.reduce((total, item) => total + item.price * item.stock, 0);
}

/** 在庫切れの商品名 */
export function findSoldOutNames(items: readonly StockItem[]): string[] {
  return items.filter((item) => item.stock <= 0).map((item) => item.name);
}

/** 在庫わずかの商品名（在庫切れは含めない） */
export function findLowStockNames(items: readonly StockItem[]): string[] {
  return items
    .filter((item) => item.stock > 0 && item.stock <= LOW_STOCK_THRESHOLD)
    .map((item) => item.name);
}

export function buildStockReport(items: readonly StockItem[]): StockReport {
  return {
    totalValue: calcStockValue(items),
    soldOutNames: findSoldOutNames(items),
    lowStockNames: findLowStockNames(items),
  };
}

export function formatStockReport(report: StockReport): string {
  const soldOut = report.soldOutNames.length === 0 ? '(なし)' : report.soldOutNames.join(' / ');
  const lowStock = report.lowStockNames.length === 0 ? '(なし)' : report.lowStockNames.join(' / ');

  return [
    `在庫金額の合計: ${report.totalValue}円`,
    `在庫切れ: ${soldOut}`,
    `在庫わずか（${LOW_STOCK_THRESHOLD}点以下）: ${lowStock}`,
  ].join('\n');
}
