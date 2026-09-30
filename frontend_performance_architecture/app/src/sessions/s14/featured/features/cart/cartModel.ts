/** カートが受け取る商品の最小限の形。catalog の Product 型には依存しない */
export type CartItemInput = { id: number; name: string; price: number };

export type CartLine = CartItemInput & { quantity: number };

/** 同じ商品なら数量を増やし、初めてなら行を足す（元の配列は変えない） */
export function addItem(lines: readonly CartLine[], item: CartItemInput): CartLine[] {
  if (!lines.some((line) => line.id === item.id)) {
    // item をそのまま広げると、渡された Product の category まで写ってしまうので項目を選んで写す
    return [...lines, { id: item.id, name: item.name, price: item.price, quantity: 1 }];
  }
  return lines.map((line) => (line.id === item.id ? { ...line, quantity: line.quantity + 1 } : line));
}

export function countOf(lines: readonly CartLine[]): number {
  return lines.reduce((sum, line) => sum + line.quantity, 0);
}

export function totalOf(lines: readonly CartLine[]): number {
  return lines.reduce((sum, line) => sum + line.price * line.quantity, 0);
}
