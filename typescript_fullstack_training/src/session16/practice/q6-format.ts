// 問題6：整形だけを担当する。order → format の一方向依存になっている。
import { calcLineTotal, calcOrderTotal, countItems } from './q6-order';
import { ORDER_LABEL, type Order, type OrderLine } from './q6-shared';

// トップレベルで ORDER_LABEL を使っても安全（q6-shared は誰も import していない）
export const HEADER = `=== ${ORDER_LABEL}確認書 ===`;

export function formatOrderLine(line: OrderLine): string {
  return `${line.name} × ${line.quantity}点 = ${calcLineTotal(line)}円`;
}

export function formatOrder(order: Order): string {
  return [
    HEADER,
    `${ORDER_LABEL} #${order.id}`,
    ...order.lines.map((line) => formatOrderLine(line)),
    `合計 ${calcOrderTotal(order)}円（${countItems(order)}点）`,
  ].join('\n');
}
