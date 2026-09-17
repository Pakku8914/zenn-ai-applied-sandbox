// 在庫の通知とレポート。
// 「外の世界に触れるもの（通知の送り先・現在時刻）は引数で受け取る」方針で書いてある。
// この方針だと、テストでモジュールごと差し替える必要がなくなる。

import type { Product } from '../session16/types';

/** 通知の送り先。関数として受け取るので、テストでは記録するだけの関数を渡せる */
export type Notifier = (message: string) => void;

/** 在庫が threshold 以下の商品を通知する。通知した件数を返す */
export function notifyLowStock(
  products: readonly Product[],
  threshold: number,
  notify: Notifier
): number {
  let count = 0;

  for (const product of products) {
    if (product.stock <= threshold) {
      notify(`${product.name}の在庫が残り${product.stock}点です`);
      count += 1;
    }
  }
  return count;
}

/** 在庫レポートの1行。現在時刻を中で取らず、引数で受け取るので結果が毎回同じになる */
export function buildStockReportLine(product: Product, now: Date): string {
  const date = now.toISOString().slice(0, 10);
  return `[${date}] ${product.name}: 在庫${product.stock}点`;
}
