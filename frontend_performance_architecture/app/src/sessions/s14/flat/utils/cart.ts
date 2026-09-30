import type { Product } from '../../../../data/products';

// Bad 例：カートの行が商品の型そのものに依存している（商品に項目が増えるとカートにも増える）
export type CartLine = Product & { quantity: number };

export function addItem(lines: readonly CartLine[], product: Product): CartLine[] {
  if (!lines.some((line) => line.id === product.id)) {
    return [...lines, { ...product, quantity: 1 }];
  }
  return lines.map((line) => (line.id === product.id ? { ...line, quantity: line.quantity + 1 } : line));
}

export function countOf(lines: readonly CartLine[]): number {
  return lines.reduce((sum, line) => sum + line.quantity, 0);
}
