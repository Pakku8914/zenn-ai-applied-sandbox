// 支払総額の内訳を表示するだけの部品（練習問題5）。
// 状態もイベントも持たないので 'use client' は書かない（クライアント側から使うことはできる）。

import { formatYen } from '@/lib/format';
import { calcRemainingForFreeShipping, type PaymentSummary } from '@/lib/pricing';

type CartSummaryProps = {
  summary: PaymentSummary;
};

export function CartSummary({ summary }: CartSummaryProps) {
  const remaining = calcRemainingForFreeShipping(summary.totalWithTax);

  return (
    <div>
      <h2>お支払い金額</h2>
      <dl>
        <dt>商品小計（税抜）</dt>
        <dd>{formatYen(summary.subtotal)}</dd>
        <dt>消費税</dt>
        <dd>{formatYen(summary.tax)}</dd>
        <dt>税込商品合計</dt>
        <dd>{formatYen(summary.totalWithTax)}</dd>
        <dt>送料</dt>
        <dd>{summary.shippingFee === 0 ? '無料' : formatYen(summary.shippingFee)}</dd>
        <dt>支払総額</dt>
        <dd>{formatYen(summary.payableAmount)}</dd>
      </dl>
      {remaining === 0 ? (
        <p>送料は無料です。</p>
      ) : (
        <p>{`あと ${formatYen(remaining)} で送料が無料になります。`}</p>
      )}
    </div>
  );
}
