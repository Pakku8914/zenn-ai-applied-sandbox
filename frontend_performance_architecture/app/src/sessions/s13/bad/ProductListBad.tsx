import type { Product } from '../../../data/products';

type Props = {
  items: readonly Product[];
  showAddButton?: boolean;
  onAdd?: (id: number) => void;
  showCompare?: boolean;
  selectedIds?: ReadonlySet<number>;
  onToggleCompare?: (id: number) => void;
};

/**
 * Bad：画面が増えるたびに boolean と省略可能なコールバックを足していった版。
 * showAddButton だけ渡して onAdd を忘れても型は通り、押しても何も起きないボタンが出る。
 * showAddButton と showCompare を両方 true にした場合の見た目は誰も決めていない。
 */
export function ProductListBad({
  items,
  showAddButton = false,
  onAdd,
  showCompare = false,
  selectedIds,
  onToggleCompare,
}: Props) {
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
            {showAddButton ? (
              <button type="button" onClick={() => onAdd?.(p.id)}>
                カートに入れる
              </button>
            ) : null}
            {showCompare ? (
              <label>
                <input
                  type="checkbox"
                  checked={selectedIds?.has(p.id) ?? false}
                  onChange={() => onToggleCompare?.(p.id)}
                />{' '}
                比較
              </label>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
