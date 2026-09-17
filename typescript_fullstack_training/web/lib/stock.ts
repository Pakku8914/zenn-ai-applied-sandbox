// 在庫引当の「判定」だけを集めた純粋なモジュール（セッション23）。
// データベースには触らないので、同じ実装を src/session23/verify.ts で検証できる。

/** 成功なら value、失敗なら error（セッション13・18で定義したものと同じ形） */
export type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };

/** 1明細あたりの数量の上限（セッション15で決めた値） */
export const MAX_CART_QUANTITY = 10;

/** 在庫引当が失敗する理由。判別タグは本書共通の kind */
export type StockFailure =
  | { kind: 'invalid_quantity'; quantity: number }
  | { kind: 'out_of_stock'; productId: number }
  | { kind: 'insufficient_stock'; productId: number; stock: number; quantity: number };

/**
 * 数量そのものの妥当性を確かめる。
 * データベースに問い合わせる前に落とせる失敗は、ここで落とす。
 */
export function judgeQuantity(quantity: number): Result<number, StockFailure> {
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_CART_QUANTITY) {
    return { kind: 'error', error: { kind: 'invalid_quantity', quantity } };
  }

  return { kind: 'ok', value: quantity };
}

/**
 * 在庫と要求数量から引当の可否を判定し、引当後の在庫数を返す。
 * これは「画面に出すための判定」であって、同時アクセスに対する保証ではない
 * （最後の砦は product-repository.ts の条件付き更新）。
 */
export function judgeReservation(
  productId: number,
  stock: number,
  quantity: number
): Result<{ nextStock: number }, StockFailure> {
  const judged = judgeQuantity(quantity);

  if (judged.kind === 'error') {
    return { kind: 'error', error: judged.error };
  }

  if (stock <= 0) {
    return { kind: 'error', error: { kind: 'out_of_stock', productId } };
  }

  if (stock < quantity) {
    return { kind: 'error', error: { kind: 'insufficient_stock', productId, stock, quantity } };
  }

  return { kind: 'ok', value: { nextStock: stock - quantity } };
}

/** 失敗を人が読める日本語にする。画面と API の両方から使う */
export function describeStockFailure(failure: StockFailure): string {
  switch (failure.kind) {
    case 'invalid_quantity':
      return `数量は1以上${MAX_CART_QUANTITY}以下の整数で指定してください: ${failure.quantity}`;
    case 'out_of_stock':
      return `在庫切れです（商品ID ${failure.productId}）`;
    case 'insufficient_stock':
      return `在庫が足りません（商品ID ${failure.productId}：在庫 ${failure.stock} / 要求 ${failure.quantity}）`;
    default: {
      const unreachable: never = failure;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}
