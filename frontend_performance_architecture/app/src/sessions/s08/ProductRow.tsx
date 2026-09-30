import { memo } from 'react';
import type { Product } from '../../data/products';
import { countRender } from './renderCount';

const priceFormat = new Intl.NumberFormat('ja-JP');

export type RowProps = {
  product: Product;
  selected: boolean;
  onSelect: (id: number) => void;
};

/** 商品1行。クリックで選択できる。本体が実行されるたびに row を1つ数える */
export function ProductRow({ product, selected, onSelect }: RowProps) {
  countRender('row');
  return (
    <li
      data-selected={selected}
      onClick={() => onSelect(product.id)}
      style={{
        borderBottom: '1px solid #ddd',
        padding: '8px 0',
        display: 'flex',
        gap: 12,
        background: selected ? '#eef4ff' : undefined,
      }}
    >
      <span style={{ width: 120 }}>{product.name}</span>
      <span style={{ width: 80, textAlign: 'right' }}>{priceFormat.format(product.price)} 円</span>
      <span style={{ color: '#666' }}>{product.category}</span>
    </li>
  );
}

/** props が前回と同じ（Object.is で比較）なら、本体を実行せずに前回の結果を使う */
export const MemoProductRow = memo(ProductRow);
