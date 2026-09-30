import { useState } from 'react';
import type { Product } from '../../data/products';
import { OVERSCAN, ROW_HEIGHT, RowCells, VIEWPORT_HEIGHT, listStyle, rowStyle, viewportStyle } from './rows';
import { computeWindow } from './windowing';

/**
 * Good 版：見えている範囲（＋オーバースキャン）だけを DOM に置く。
 * scrollTop はこのコンポーネントの中に閉じ込める。親に置くと、スクロールのたびに親の絞り込み（全件の filter）まで再実行される。
 */
export function VirtualProductList({ items }: { items: readonly Product[] }) {
  const [scrollTop, setScrollTop] = useState(0);
  const range = computeWindow({
    itemCount: items.length,
    rowHeight: ROW_HEIGHT,
    viewportHeight: VIEWPORT_HEIGHT,
    scrollTop,
    overscan: OVERSCAN,
  });
  const visible = items.slice(range.start, range.end);

  return (
    <section>
      <h2>商品一覧（{items.length} 件）</h2>
      <div data-viewport="true" tabIndex={0} style={viewportStyle} onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}>
        {/* 描かない行の分の高さを上下のスペーサーで埋め、スクロールバーの長さを全件分に保つ */}
        <div style={{ height: range.paddingTop }} />
        <ul style={listStyle}>
          {visible.map((p, i) => (
            // DOM に無い行があることを支援技術に伝える最低限の属性（詳しくは S16）
            <li key={p.id} style={rowStyle} aria-setsize={items.length} aria-posinset={range.start + i + 1}>
              <RowCells product={p} />
            </li>
          ))}
        </ul>
        <div style={{ height: range.paddingBottom }} />
      </div>
    </section>
  );
}
