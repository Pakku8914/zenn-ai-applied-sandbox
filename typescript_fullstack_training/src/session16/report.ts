// 出力の組み立て。データ・計算・検証のファイルを束ねるだけで、自分では計算しない。
import { describeLine, toCartLines } from './cart';
import { toProduct } from './parse';
import { buildPaymentSummary, resolveDiscountRule } from './pricing';
import { brokenCartItems, cartItems } from './shop-data';
import type { MemberRank } from './types';

const MUG_JSON = '{"id":3,"name":"マグカップ","price":2350,"stock":3,"categoryId":2}';
const BROKEN_JSON = '{"id":3,"name":"マグカップ","price":"2350"}';

export function buildReport(rank: MemberRank): string {
  const lines = toCartLines(cartItems);
  const summary = buildPaymentSummary(lines, resolveDiscountRule(rank));
  const first = lines[0]; // noUncheckedIndexedAccess のため CartLine | undefined
  const output: string[] = ['--- カートの明細 ---'];

  for (const line of lines) {
    output.push(describeLine(line));
  }

  output.push('--- お支払い ---');
  output.push(`小計: ${summary.subtotal}円`);
  output.push(`割引: -${summary.discountAmount}円`);
  output.push(`消費税: ${summary.tax}円`);
  output.push(`送料: ${summary.shippingFee}円`);
  output.push(`お支払総額: ${summary.payableAmount}円`);

  output.push('--- 欠けた値の扱い ---');
  // first が undefined なら .product にも進まず、?? が既定値を用意する
  output.push(`先頭の明細: ${first?.product.name ?? '(カートは空です)'}`);
  output.push(`商品が消えた明細を除いた件数: ${toCartLines(brokenCartItems).length}件`);
  output.push(`JSON から復元: ${toProduct(MUG_JSON)?.name ?? '(形が違います)'}`);
  output.push(`壊れた JSON: ${toProduct(BROKEN_JSON)?.name ?? '(形が違います)'}`);

  return output.join('\n');
}
