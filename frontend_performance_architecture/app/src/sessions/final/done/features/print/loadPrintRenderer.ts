import type { Product } from '../../../../../data/products';

export type RenderCard = (product: Product) => string;

let pending: Promise<RenderCard> | null = null;

/**
 * 印刷用 HTML を作る関数を、初めて必要になったときに読み込む（動的 import。S05）。
 * react-dom/server ごと別チャンクになり、初期 JS から外れる。2 回目以降は同じ Promise を返す。
 * 読み込みに失敗したら覚えておかない（次に押されたときにもう一度取りに行く）。
 */
export function loadPrintRenderer(): Promise<RenderCard> {
  if (pending === null) {
    pending = import('../../../../s05/print/renderPrintCard').then(
      (m) => m.renderPrintCard,
      (error: unknown) => {
        pending = null;
        throw error;
      },
    );
  }
  return pending;
}
