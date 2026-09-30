import { useCallback, useDeferredValue, useState } from 'react';
import type { Product } from '../../data/products';
import { CatalogFrame } from './CatalogFrame';
import { MemoProductList } from './MemoProductList';
import { countRender } from './renderCount';

type Props = { title: string; products: readonly Product[] };

/**
 * useDeferredValue 版：入力欄は keyword で即座に更新し、一覧には「遅れてついてくる」値を渡す。
 * 一覧の再レンダリングは中断可能な優先度の低い更新になり、次のキー入力が来たら後回しにされる。
 */
export function CatalogDeferred({ title, products }: Props) {
  countRender('catalog');
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const deferredKeyword = useDeferredValue(keyword);
  const isStale = keyword !== deferredKeyword;
  const handleSelect = useCallback((id: number) => setSelectedId(id), []);

  return (
    <CatalogFrame title={title} keyword={keyword} onKeywordChange={setKeyword}>
      {/* 古い結果を表示している間は薄くする。opacity は合成だけで済むプロパティ */}
      <div style={{ opacity: isStale ? 0.6 : 1 }}>
        <MemoProductList
          products={products}
          keyword={deferredKeyword}
          selectedId={selectedId}
          onSelect={handleSelect}
        />
      </div>
    </CatalogFrame>
  );
}
