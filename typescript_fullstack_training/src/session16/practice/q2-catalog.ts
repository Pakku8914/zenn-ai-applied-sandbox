// 問題2：窓口（バレル）ファイル。使う側はこのファイルだけを import すればよい。
// 値は export、型は export type で再エクスポートする（verbatimModuleSyntax）。
export { findProductById } from '../cart';
export { cartItems, products } from '../shop-data';
export type { CartItem, Product } from '../types';
