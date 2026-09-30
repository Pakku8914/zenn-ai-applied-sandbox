import type { CSSProperties } from 'react';
import type { Product } from '../../data/products';

/** 行の高さ・表示枠の高さ・オーバースキャン。範囲の計算・行のスタイル・スケルトンがすべてこの値を使う */
export const ROW_HEIGHT = 40;
export const VIEWPORT_HEIGHT = 400;
export const OVERSCAN = 5;

export const pageStyle: CSSProperties = { fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' };

/** スクロールする表示枠。全件描画版と仮想化版で同じ枠を使い、違いを「DOM に置く行の数」だけにする */
export const viewportStyle: CSSProperties = { height: VIEWPORT_HEIGHT, overflowY: 'auto', border: '1px solid #ddd' };

export const listStyle: CSSProperties = { listStyle: 'none', padding: 0, margin: 0 };

/** 高さを固定する（border-box なので下線込みで 40px）。仮想化の計算はこの高さを前提にしている */
export const rowStyle: CSSProperties = {
  boxSizing: 'border-box',
  height: ROW_HEIGHT,
  borderBottom: '1px solid #ddd',
  display: 'flex',
  alignItems: 'center',
  gap: 12,
};

/** 行の中身。出発点の ProductList と同じ 3 つの span */
export function RowCells({ product }: { product: Product }) {
  return (
    <>
      <span style={{ width: 120 }}>{product.name}</span>
      <span style={{ width: 80, textAlign: 'right' }}>{product.price} 円</span>
      <span style={{ color: '#666' }}>{product.category}</span>
    </>
  );
}
