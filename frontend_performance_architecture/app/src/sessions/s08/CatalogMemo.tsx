import { useCallback, useMemo, useState } from 'react';
import type { Product } from '../../data/products';
import { CatalogFrame } from './CatalogFrame';
import { MemoProductRow } from './ProductRow';
import { countRender } from './renderCount';

type Props = { title: string; products: readonly Product[] };

/**
 * メモ化版：行を memo で包み、onSelect を useCallback で固定する。
 * 入力で絞り込み結果が変わっても、残った行の props は前回と同じなので行は再レンダリングされない。
 */
export function CatalogMemo({ title, products }: Props) {
  countRender('catalog');
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // 行を選んだだけ（keyword は同じ）のときに、20,000 件の絞り込みをやり直さない
  const filtered = useMemo(() => products.filter((p) => p.name.includes(keyword)), [products, keyword]);
  // 依存が空なので、同じ関数がずっと使われる（setSelectedId は React が固定してくれる）
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
