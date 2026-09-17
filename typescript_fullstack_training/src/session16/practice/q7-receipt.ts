// 問題7：検証済みの入力から注文確認書を組み立てる。計算は ../pricing に任せる。
import { describeLine, findProductById } from '../cart';
import { buildPaymentSummary, resolveDiscountRule } from '../pricing';
import type { CartLine, MemberRank, PaymentSummary } from '../types';
import { toOrderRequest, type OrderRequest } from './q7-input';

export type Receipt = {
  rank: MemberRank;
  lines: readonly CartLine[];
  skippedProductIds: readonly number[];
  summary: PaymentSummary;
};

export function buildReceipt(request: OrderRequest): Receipt {
  const lines: CartLine[] = [];
  const skippedProductIds: number[] = [];

  for (const item of request.items) {
    const product = findProductById(item.productId);
    if (product === undefined) {
      skippedProductIds.push(item.productId);
      continue;
    }
    lines.push({ product, quantity: item.quantity });
  }

  return {
    rank: request.rank,
    lines,
    skippedProductIds,
    summary: buildPaymentSummary(lines, resolveDiscountRule(request.rank)),
  };
}

export function formatReceipt(receipt: Receipt): string {
  const output: string[] = ['=== 注文確認書 ==='];

  for (const line of receipt.lines) {
    output.push(describeLine(line));
  }

  if (receipt.skippedProductIds.length > 0) {
    output.push(
      `取り扱いのない商品を除外しました: productId=${receipt.skippedProductIds.join(', ')}`
    );
  }

  const summary = receipt.summary;
  output.push(`小計: ${summary.subtotal}円`);
  output.push(`割引（${receipt.rank}）: -${summary.discountAmount}円`);
  output.push(`消費税: ${summary.tax}円`);
  output.push(`送料: ${summary.shippingFee}円`);
  output.push(`お支払総額: ${summary.payableAmount}円`);

  return output.join('\n');
}

/** JSON 文字列から確認書のテキストまでを一気に組み立てる */
export function buildReceiptText(text: string): string {
  const request = toOrderRequest(text);

  if (request === undefined) {
    return '(入力の形が正しくありません)';
  }
  return formatReceipt(buildReceipt(request));
}
