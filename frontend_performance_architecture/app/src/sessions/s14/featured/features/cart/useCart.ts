import { useState } from 'react';
import { addItem, type CartItemInput, type CartLine } from './cartModel';

/** カートの状態。状態の持ち方を変えても、使う側（app）は lines と add しか知らない */
export function useCart(initialLines: readonly CartLine[] = []) {
  const [lines, setLines] = useState<readonly CartLine[]>(initialLines);
  const add = (item: CartItemInput) => setLines((current) => addItem(current, item));
  return { lines, add };
}
