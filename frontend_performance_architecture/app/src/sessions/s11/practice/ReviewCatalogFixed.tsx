import { useState } from 'react';
import type { Product } from '../../../data/products';
import { OVERSCAN, ROW_HEIGHT, VIEWPORT_HEIGHT } from '../rows';
import { computeWindow } from '../windowing';

/**
 * 練習問題7の解答：scrollTop を一覧の中へ移し、スクロールで絞り込み・並び替えが再実行されないようにする。
 * あわせて key を配列の添字から商品 id に直す。
 */
export function ReviewCatalogFixed({ products }: { products: readonly Product[] }) {
  const [keyword, setKeyword] = useState('');
  // filter が新しい配列を返すので、sort で元の products（props）を書き換えることはない
  const sorted = products.filter((p) => p.name.includes(keyword)).sort((a, b) => a.price - b.price);

  return (
    <main>
      <input id="keyword" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
      <SortedVirtualList items={sorted} />
    </main>
  );
}

function SortedVirtualList({ items }: { items: readonly Product[] }) {
  const [scrollTop, setScrollTop] = useState(0);
  const range = computeWindow({
    itemCount: items.length,
    rowHeight: ROW_HEIGHT,
    viewportHeight: VIEWPORT_HEIGHT,
    scrollTop,
    overscan: OVERSCAN,
  });

  return (
    <div style={{ height: VIEWPORT_HEIGHT, overflowY: 'auto' }} onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}>
      <div style={{ height: range.paddingTop }} />
      <ul>
        {items.slice(range.start, range.end).map((p) => (
          <li key={p.id} style={{ boxSizing: 'border-box', height: ROW_HEIGHT }}>
            {p.name} {p.price} 円
          </li>
        ))}
      </ul>
      <div style={{ height: range.paddingBottom }} />
    </div>
  );
}
