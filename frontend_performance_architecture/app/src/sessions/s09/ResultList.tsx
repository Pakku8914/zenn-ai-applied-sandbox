import type { Product } from '../../data/products';
import { countRender } from './renderCount';

type Props = {
  items: readonly Product[];
  onAdd?: (id: number) => void;
};

/** 出発点の ProductList と同じ見た目で、受け取った商品を描くだけの部品（状態を持たない） */
export function ResultList({ items, onAdd }: Props) {
  countRender('ResultList');
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
            <span style={{ width: 60, color: '#666' }}>{p.category}</span>
            {onAdd ? (
              <button type="button" onClick={() => onAdd(p.id)}>
                カートに入れる
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** 状態を読まない静的な部品。Provider の再レンダリングに巻き込まれないことを確かめるために数える */
export function PageIntro() {
  countRender('PageIntro');
  return <p style={{ color: '#666' }}>商品名とカテゴリで絞り込めます。</p>;
}
