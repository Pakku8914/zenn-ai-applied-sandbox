// セッション18で作った reserveStock（Result を返す版）と同じ判定を、
// 「例外を投げる版」でも書いてみる。テストの書き味を比べるために置いてある。
//
// 実装の手本は Result 版（src/session18 の shop.ts）のほう。
// こちらは「例外のテストはこう書く」を学ぶための対比用。

import type { CatalogItem } from '../session17/catalog';
import type { Reservation } from '../session18/shop';

/** 在庫不足を例外で表すカスタムエラー（セッション18の out_of_stock に対応する） */
export class StockShortageError extends Error {
  override readonly name = 'StockShortageError';
  readonly productName: string;
  readonly requested: number;
  readonly available: number;

  constructor(productName: string, requested: number, available: number) {
    super(`${productName}の在庫が足りません（希望 ${requested}点 / 在庫 ${available}点）`);
    this.productName = productName;
    this.requested = requested;
    this.available = available;
  }
}

/** 例外を投げる版の在庫引当。成功したら明細を返す */
export function reserveStockOrThrow(item: CatalogItem, quantity: number): Reservation {
  // 数量が正の整数でないのは呼び出し側のバグ。回復できないので例外にする
  if (!Number.isInteger(quantity) || quantity < 1) {
    throw new RangeError(`数量は1以上の整数で指定してください: ${quantity}`);
  }

  if (item.stock < quantity) {
    throw new StockShortageError(item.name, quantity, item.stock);
  }

  return {
    productId: item.id,
    productName: item.name,
    quantity,
    lineTotal: item.price * quantity,
  };
}
