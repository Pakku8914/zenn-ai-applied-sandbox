import type { Product } from '../../data/products';
import { RowCells, listStyle, rowStyle, viewportStyle } from './rows';

/** Bad 版：表示枠は 400px（10 行分）しかないのに、全件を DOM に置く */
export function PlainProductList({ items }: { items: readonly Product[] }) {
  return (
    <section>
      <h2>商品一覧（{items.length} 件）</h2>
      {/* スクロールできる領域はキーボードでも操作できるよう tabIndex を付ける */}
      <div data-viewport="true" tabIndex={0} style={viewportStyle}>
        <ul style={listStyle}>
          {items.map((p) => (
            <li key={p.id} style={rowStyle}>
              <RowCells product={p} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
