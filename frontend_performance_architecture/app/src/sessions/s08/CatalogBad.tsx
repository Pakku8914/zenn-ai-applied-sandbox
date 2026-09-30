import { useState } from 'react';
import type { Product } from '../../data/products';
import { CatalogFrame } from './CatalogFrame';
import { ProductRow } from './ProductRow';
import { countRender } from './renderCount';

type Props = { title: string; products: readonly Product[] };

/**
 * Bad 版：メモ化なし。1文字入力するたびに、絞り込み後の全行が再レンダリングされる。
 */
export function CatalogBad({ title, products }: Props) {
  countRender('catalog');
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const filtered = products.filter((p) => p.name.includes(keyword));

  return (
    <CatalogFrame title={title} keyword={keyword} onKeywordChange={setKeyword}>
      <section>
        <h2>商品一覧（{filtered.length} 件）</h2>
        <ul style={{ listStyle: 'none', padding: 0 }}>
          {filtered.map((p) => (
            <ProductRow
              key={p.id}
              product={p}
              selected={p.id === selectedId}
              onSelect={(id) => setSelectedId(id)}
            />
          ))}
        </ul>
      </section>
    </CatalogFrame>
  );
}
