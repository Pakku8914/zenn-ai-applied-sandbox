import { useCallback, useState } from 'react';
import type { Product } from '../../../data/products';
import { CatalogFrame } from '../CatalogFrame';
import { MemoProductRow } from '../ProductRow';
import { countRender } from '../renderCount';

type Props = { title: string; products: readonly Product[] };

/**
 * 問題4の解答：CatalogMemoInline の onSelect を useCallback で固定しただけの版。
 * 直したのは「毎回新しい関数を渡していた」1か所で、ほかは CatalogMemoInline と同じ。
 */
export function CatalogFixed({ title, products }: Props) {
  countRender('catalog');
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const filtered = products.filter((p) => p.name.includes(keyword));
  const handleSelect = useCallback((id: number) => setSelectedId(id), []);

  return (
    <CatalogFrame title={title} keyword={keyword} onKeywordChange={setKeyword}>
      <section>
        <h2>商品一覧（{filtered.length} 件）</h2>
        <ul style={{ listStyle: 'none', padding: 0 }}>
          {filtered.map((p) => (
            <MemoProductRow key={p.id} product={p} selected={p.id === selectedId} onSelect={handleSelect} />
          ))}
        </ul>
      </section>
    </CatalogFrame>
  );
}
