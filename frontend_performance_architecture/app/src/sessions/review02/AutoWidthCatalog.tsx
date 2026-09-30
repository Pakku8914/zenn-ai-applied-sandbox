import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { Product } from '../../data/products';
import { CatalogFrame } from '../s08/CatalogFrame';
import { MemoProductRow } from '../s08/ProductRow';
import { countRender } from '../s08/renderCount';

type Props = { title: string; products: readonly Product[] };

/**
 * 横断復習②の「入力すると固まる画面」の1つ。一覧の行は memo と useCallback で守られている。
 * 絞り込むたびに「商品名と価格の列幅を中身に合わせる」処理が、1行ずつ書く → 読む → 書くを繰り返す。
 */
export function AutoWidthCatalog({ title, products }: Props) {
  countRender('catalog');
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const filtered = useMemo(() => products.filter((p) => p.name.includes(keyword)), [products, keyword]);
  const handleSelect = useCallback((id: number) => setSelectedId(id), []);

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    for (const row of list.querySelectorAll<HTMLElement>('li')) {
      // 1列目（商品名）と2列目（価格）
      for (const cell of [row.children[0], row.children[1]]) {
        if (!(cell instanceof HTMLElement)) continue;
        cell.style.width = 'auto'; // 書き込み：中身の幅を測るために固定幅を外す
        const natural = cell.scrollWidth; // 読み取り：直前の書き込みを反映するため、強制同期レイアウトが走る
        cell.style.width = `${natural + 8}px`; // 書き込み：次の読み取りで、またレイアウトが必要になる
      }
    }
  }, [filtered]);

  return (
    <CatalogFrame title={title} keyword={keyword} onKeywordChange={setKeyword}>
      <section>
        <h2>商品一覧（{filtered.length} 件）</h2>
        <ul ref={listRef} style={{ listStyle: 'none', padding: 0 }}>
          {filtered.map((p) => (
            <MemoProductRow key={p.id} product={p} selected={p.id === selectedId} onSelect={handleSelect} />
          ))}
        </ul>
      </section>
    </CatalogFrame>
  );
}
