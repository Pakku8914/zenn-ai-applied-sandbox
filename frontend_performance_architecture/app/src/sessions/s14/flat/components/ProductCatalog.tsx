import { useState } from 'react';
import type { Product } from '../../../../data/products';
import { addItem, type CartLine } from '../utils/cart';
import { filterProducts } from '../utils/filter';
import { formatYen } from '../utils/format';
import { Button } from './Button';

type Props = {
  items: readonly Product[];
  // Bad 例：一覧がカートの中身と更新方法まで受け取り、自分でカートを書き換えている
  lines: readonly CartLine[];
  setLines: (lines: CartLine[]) => void;
  initialKeyword?: string;
};

export function ProductCatalog({ items, lines, setLines, initialKeyword = '' }: Props) {
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
              <Button onClick={() => setLines(addItem(lines, p))}>カートに入れる</Button>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
