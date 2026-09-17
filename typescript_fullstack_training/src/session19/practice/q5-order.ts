// 問題5：注文を確定する処理。
// 通知の送り先を引数で受け取るので、テストでモジュールを差し替える必要がない。

import { isWithinQuantityLimit } from '../../session16/cart';
import { buildPaymentSummary, resolveDiscountRule } from '../../session16/pricing';
import type { CartLine, MemberRank, PaymentSummary } from '../../session16/types';
import type { Notifier } from '../report';

export type PlaceOrderResult =
  | { kind: 'ok'; summary: PaymentSummary }
  | { kind: 'error'; message: string };

export function placeOrder(
  lines: readonly CartLine[],
  rank: MemberRank,
  notify: Notifier
): PlaceOrderResult {
  if (lines.length === 0) {
    return { kind: 'error', message: 'カートが空です' };
  }

  const invalid = lines.find((line) => !isWithinQuantityLimit(line));

  if (invalid !== undefined) {
    return { kind: 'error', message: `数量が上限を超えています: ${invalid.product.name}` };
  }

  const summary = buildPaymentSummary(lines, resolveDiscountRule(rank));
  notify(`注文を受け付けました（${summary.payableAmount}円）`);

  return { kind: 'ok', summary };
}
