import { memo, useCallback, useDeferredValue, useMemo, useState } from 'react';
import type { Product } from '../../../data/products';
import { CatalogFrame } from '../CatalogFrame';
import { MemoProductRow } from '../ProductRow';
import { countRender } from '../renderCount';

type ListProps = {
  products: readonly Product[];
  keyword: string;
  selectedId: number | null;
  onSelect: (id: number) => void;
};

/** 一覧を memo で包める単位に切り出す。急ぎの再レンダリングでは props が同じなので丸ごと飛ばされる */
const DeferredList = memo(function DeferredList({ products, keyword, selectedId, onSelect }: ListProps) {
  countRender('list');
  const filtered = useMemo(() => products.filter((p) => p.name.includes(keyword)), [products, keyword]);
  return (
    <section>
      <h2>商品一覧（{filtered.length} 件）</h2>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {filtered.map((p) => (
          <MemoProductRow key={p.id} product={p} selected={p.id === selectedId} onSelect={onSelect} />
        ))}
      </ul>
    </section>
  );
});

type Props = { title: string; products: readonly Product[] };

/** 問題6の解答：入力欄は keyword で即座に描き、一覧には遅れてついてくる値を渡す */
export function CatalogMyDeferred({ title, products }: Props) {
  countRender('catalog');
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const deferredKeyword = useDeferredValue(keyword);
  const handleSelect = useCallback((id: number) => setSelectedId(id), []);

  return (
    <CatalogFrame title={title} keyword={keyword} onKeywordChange={setKeyword}>
      <div data-stale={keyword !== deferredKeyword} style={{ opacity: keyword !== deferredKeyword ? 0.6 : 1 }}>
        <DeferredList products={products} keyword={deferredKeyword} selectedId={selectedId} onSelect={handleSelect} />
      </div>
    </CatalogFrame>
  );
}
