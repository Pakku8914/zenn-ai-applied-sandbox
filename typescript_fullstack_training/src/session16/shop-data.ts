// 商品マスタとカートのデータ。requirements.md のマスタと同じ値。
import type { CartItem, Product } from './types';

/** 商品マスタ（本書共通の5件） */
export const products: readonly Product[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

/** userId=1 のカートの中身 */
export const cartItems: readonly CartItem[] = [
  { id: 1, userId: 1, productId: 1, quantity: 2 },
  { id: 2, userId: 1, productId: 3, quantity: 1 },
];

/** 商品が削除されてしまったカート（productId=99 はもう存在しない） */
export const brokenCartItems: readonly CartItem[] = [
  { id: 1, userId: 2, productId: 1, quantity: 1 },
  { id: 2, userId: 2, productId: 99, quantity: 1 },
];
