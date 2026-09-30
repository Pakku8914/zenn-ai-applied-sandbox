'use client';

import { useEffect, useState } from 'react';
import { ProductRows } from '../../lib/s12/ProductRows';
import type { Product } from '../../lib/s12/products';
import { markHydrated } from '../../lib/s12/browser';

/**
 * 境界を根元に置いた版。入力欄だけでなく一覧まで 'use client' の内側にあるため、
 * ProductRows のコードもクライアントのバンドルに入り、2,000 行すべてがハイドレーションの対象になる。
 */
export function ClientCatalog({ products }: { products: Product[] }) {
  const [keyword, setKeyword] = useState('');

  useEffect(markHydrated, []);

  const filtered = products.filter((p) => p.name.includes(keyword));
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
      <ProductRows products={filtered} />
    </>
  );
}
