import { useState } from 'react';
import type { Product } from '../../../../../data/products';
import { formatYen } from '../../shared/lib/format';
import { Button } from '../../shared/ui/Button';
import { filterProducts } from './filterProducts';

type Props = {
  items: readonly Product[];
  /** 「カートに入れる」が押されたとき。カートの存在は知らず、押された商品を渡すだけ */
  onAdd: (product: Product) => void;
  initialKeyword?: string;
};

export function ProductCatalog({ items, onAdd, initialKeyword = '' }: Props) {
  const [keyword, setKeyword] = useState(initialKeyword);
  const visible = filterProducts(items, keyword);

  return (
    <>
      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        placeholder="例: 商品1"
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />
      <section>
        <h2>商品一覧（{visible.length} 件）</h2>
        <ul style={{ listStyle: 'none', padding: 0 }}>
          {visible.map((p) => (
            <li key={p.id} style={{ borderBottom: '1px solid #ddd', padding: '8px 0', display: 'flex', gap: 12 }}>
              <span style={{ width: 120 }}>{p.name}</span>
              <span style={{ width: 80, textAlign: 'right' }}>{formatYen(p.price)}</span>
              <span style={{ color: '#666' }}>{p.category}</span>
              <Button onClick={() => onAdd(p)}>カートに入れる</Button>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
