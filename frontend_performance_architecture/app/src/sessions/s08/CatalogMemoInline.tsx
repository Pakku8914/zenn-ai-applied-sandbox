import { useState } from 'react';
import type { Product } from '../../data/products';
import { CatalogFrame } from './CatalogFrame';
import { MemoProductRow } from './ProductRow';
import { countRender } from './renderCount';

type Props = { title: string; products: readonly Product[] };

/**
 * 「メモ化を入れても変わらない」版：行を memo で包んだが、onSelect に毎回新しい関数を渡している。
 * props の比較が毎回「違う」になるため、再レンダリング回数は Bad 版と完全に同じになる。
 */
export function CatalogMemoInline({ title, products }: Props) {
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
            <MemoProductRow
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
