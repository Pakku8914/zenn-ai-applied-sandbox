import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import type { Product } from '../../data/products';
import { OVERSCAN, ROW_HEIGHT, VIEWPORT_HEIGHT, listStyle, rowStyle, viewportStyle } from '../s11/rows';
import { computeWindow } from '../s11/windowing';
import { nextIndex, renderIndices, scrollTopToReveal } from './a11yModel';

const nameButtonStyle: CSSProperties = { width: 120, textAlign: 'left', background: 'none', border: 'none', padding: 4, font: 'inherit' };

type Props = {
  items: readonly Product[];
  onOpen: (product: Product) => void;
};

/**
 * Good 版：仮想化したまま、キーボードで全行を操作できる一覧。
 * - Tab で止まるのは「いまの行」のボタン 1 つだけ（ロービングタブインデックス）。↑↓・Home・End で行を移る
 * - フォーカス中の行は、表示範囲の外にスクロールされても DOM に残す（renderIndices の pinned）
 * - 行は絶対配置にして、範囲の外にある 1 行を残してもレイアウトが崩れないようにする
 */
export function AccessibleList({ items, onOpen }: Props) {
  const [scrollTop, setScrollTop] = useState(0);
  const [active, setActive] = useState(0);
  const viewportRef = useRef<HTMLDivElement>(null);
  const focusPending = useRef(false);

  const range = computeWindow({
    itemCount: items.length,
    rowHeight: ROW_HEIGHT,
    viewportHeight: VIEWPORT_HEIGHT,
    scrollTop,
    overscan: OVERSCAN,
  });
  const indices = renderIndices(range.start, range.end, active);

  // キー操作で active が変わったら、描き終わったあとで新しい行にフォーカスを移す
  useEffect(() => {
    if (!focusPending.current) return;
    focusPending.current = false;
    viewportRef.current?.querySelector<HTMLButtonElement>(`[data-index="${active}"]`)?.focus();
  }, [active]);

  function onKeyDown(e: KeyboardEvent<HTMLUListElement>) {
    const next = nextIndex(active, e.key, items.length, { orientation: 'vertical', wrap: false });
    if (next === null) return;
    e.preventDefault(); // ↑↓ で表示枠がスクロールしてしまうのを止める
    if (next === active) return;
    const viewport = viewportRef.current;
    if (viewport) viewport.scrollTop = scrollTopToReveal(next, viewport.scrollTop, ROW_HEIGHT, VIEWPORT_HEIGHT);
    focusPending.current = true;
    setActive(next);
  }

  return (
    <div ref={viewportRef} data-viewport="true" style={viewportStyle} onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}>
      <ul aria-labelledby="list-heading" onKeyDown={onKeyDown} style={{ ...listStyle, position: 'relative', height: range.totalHeight }}>
        {indices.map((index) => {
          const product = items[index];
          if (product === undefined) return null;
          return (
            <li
              key={product.id}
              style={{ ...rowStyle, position: 'absolute', top: index * ROW_HEIGHT, left: 0, right: 0 }}
              // DOM に無い行があっても「全何件中の何件目か」を支援技術に伝える
              aria-setsize={items.length}
              aria-posinset={index + 1}
            >
              <button
                type="button"
                data-index={index}
                tabIndex={index === active ? 0 : -1}
                aria-haspopup="dialog"
                onFocus={() => setActive(index)}
                onClick={() => onOpen(product)}
                style={nameButtonStyle}
              >
                {product.name}
              </button>
              <span style={{ width: 80, textAlign: 'right' }}>{product.price} 円</span>
              <span style={{ color: '#666' }}>{product.category}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
