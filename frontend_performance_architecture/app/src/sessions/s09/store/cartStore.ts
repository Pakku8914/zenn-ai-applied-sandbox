import { products } from '../../../data/products';
import { countInCategory } from '../catalogQuery';
import { createStore } from './createStore';

export type CartState = { ids: readonly number[] };

export const cartStore = createStore<CartState>({ ids: [] });

/** 更新関数はモジュールから直接呼べる。Context で配る必要がない */
export function addToCart(id: number): void {
  cartStore.setState((s) => ({ ids: [...s.ids, id] }));
}

export const selectCount = (s: CartState): number => s.ids.length;
export const selectBookCount = (s: CartState): number => countInCategory(s.ids, '書籍', products);
