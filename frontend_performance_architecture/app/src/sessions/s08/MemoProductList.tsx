import { memo, useMemo } from 'react';
import type { Product } from '../../data/products';
import { MemoProductRow } from './ProductRow';
import { countRender } from './renderCount';

type Props = {
  products: readonly Product[];
  keyword: string;
  selectedId: number | null;
  onSelect: (id: number) => void;
};

function ProductListBody({ products, keyword, selectedId, onSelect }: Props) {
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
}

/**
 * 一覧全体を memo で包む。useDeferredValue / useTransition の版は、入力欄の更新（急ぎ）で
 * 親が再レンダリングされても、一覧は「古い keyword のまま」なのでここで丸ごと飛ばされる。
 */
export const MemoProductList = memo(ProductListBody);
