import { useCallback, useMemo, useState } from 'react';
import type { Product } from '../../data/products';
import { buildPointsSync, toPolyline } from '../s07/points';
import { CatalogFrame } from '../s08/CatalogFrame';
import { MemoProductRow } from '../s08/ProductRow';
import { countRender } from '../s08/renderCount';

type Props = { title: string; products: readonly Product[] };

/**
 * 横断復習②の「入力すると固まる画面」の1つ。一覧の行は memo と useCallback で守られている。
 * 絞り込むたびに、一覧の上の「売れ筋グラフ」の点列を作り直す。
 * 計算の中身は出発点 HeavyChart と同じ（練習用に固定の重さにしてある）。
 * useMemo で包んであるが、依存の filtered が入力のたびに変わるので、毎回計算される。
 */
export function ChartOnTypeCatalog({ title, products }: Props) {
  countRender('catalog');
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const filtered = useMemo(() => products.filter((p) => p.name.includes(keyword)), [products, keyword]);
  const points = useMemo(() => buildPointsSync(), [filtered]);
  const handleSelect = useCallback((id: number) => setSelectedId(id), []);

  return (
    <CatalogFrame title={title} keyword={keyword} onKeywordChange={setKeyword}>
      <figure style={{ margin: '0 0 16px' }}>
        <figcaption>売れ筋グラフ（{filtered.length} 件）</figcaption>
        <svg width={600} height={160} role="img" aria-label="売れ筋グラフ">
          <polyline points={toPolyline(points)} fill="none" stroke="#3b82f6" strokeWidth={2} />
        </svg>
      </figure>
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
