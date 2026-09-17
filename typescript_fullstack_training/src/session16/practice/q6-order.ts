// 問題6：計算だけを担当する。整形（q6-format.ts）を import しないので輪にならない。
import type { Order, OrderLine } from './q6-shared';

export function calcLineTotal(line: OrderLine): number {
  return line.unitPrice * line.quantity;
}

export function calcOrderTotal(order: Order): number {
  return order.lines.reduce((total, line) => total + calcLineTotal(line), 0);
}

export function countItems(order: Order): number {
  return order.lines.reduce((total, line) => total + line.quantity, 0);
}

/** 動作確認用の注文（商品マスタの id=1 と id=3 を使っている） */
export const SAMPLE_ORDER: Order = {
  id: 1001,
  lines: [
    { productId: 1, name: 'ラベンダーの石けん', unitPrice: 480, quantity: 2 },
    { productId: 3, name: 'マグカップ', unitPrice: 2350, quantity: 1 },
  ],
};
