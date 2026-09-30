import type { Product } from '../../../data/products';
import { assertNever } from '../../s10/requestState';

/**
 * 一覧の使われ方。モードごとに必要な値が違うので、boolean の組み合わせではなく
 * 判別可能ユニオンにする（「カートに入れるのにコールバックが無い」を型のうえで作れない）。
 */
export type ListMode =
  | { kind: 'browse' }
  | { kind: 'cart'; onAdd: (id: number) => void }
  | { kind: 'compare'; selectedIds: ReadonlySet<number>; onToggle: (id: number) => void };

const BROWSE: ListMode = { kind: 'browse' };

type Props = {
  items: readonly Product[];
  mode?: ListMode;
};

/** 表示専用の部品。受け取った商品を描くだけで、絞り込みもデータ取得も知らない */
export function ProductListView({ items, mode = BROWSE }: Props) {
  return (
    <section>
      <h2>商品一覧（{items.length} 件）</h2>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {items.map((p) => (
          <li
            key={p.id}
            style={{ borderBottom: '1px solid #ddd', padding: '8px 0', display: 'flex', gap: 12 }}
          >
            <span style={{ width: 120 }}>{p.name}</span>
            <span style={{ width: 80, textAlign: 'right' }}>{p.price} 円</span>
            <span style={{ color: '#666' }}>{p.category}</span>
            <RowAction mode={mode} id={p.id} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/** 行の右端に出す操作。モードを足したら case を足さないと assertNever で型エラーになる */
function RowAction({ mode, id }: { mode: ListMode; id: number }) {
  switch (mode.kind) {
    case 'browse':
      return null;
    case 'cart':
      return (
        <button type="button" onClick={() => mode.onAdd(id)}>
          カートに入れる
        </button>
      );
    case 'compare':
      return (
        <label>
          <input type="checkbox" checked={mode.selectedIds.has(id)} onChange={() => mode.onToggle(id)} /> 比較
        </label>
      );
    default:
      return assertNever(mode);
  }
}
