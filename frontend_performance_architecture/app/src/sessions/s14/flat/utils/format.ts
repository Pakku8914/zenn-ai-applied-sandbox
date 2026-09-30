import type { CartLine } from './cart';

export function formatYen(amount: number): string {
  return `${amount.toLocaleString('ja-JP')} 円`;
}

// Bad 例：誰でも使う「共通の道具」の中に、カートの計算が紛れ込んでいる
export function formatCartTotal(lines: readonly CartLine[]): string {
  return formatYen(lines.reduce((sum, line) => sum + line.price * line.quantity, 0));
}
