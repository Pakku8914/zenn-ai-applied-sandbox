import { products } from '../data/products';

type Props = {
  keyword: string;
};

/**
 * 2,000 件を毎回すべて描画する。仮想化もメモ化もしていない。
 * 入力するたびに全件の再レンダリングが走るため、INP が悪化する。
 */
export function ProductList({ keyword }: Props) {
  const filtered = products.filter((p) => p.name.includes(keyword));

  return (
    <section>
      <h2>商品一覧（{filtered.length} 件）</h2>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {filtered.map((p) => (
          <li
            key={p.id}
            style={{ borderBottom: '1px solid #ddd', padding: '8px 0', display: 'flex', gap: 12 }}
          >
            <span style={{ width: 120 }}>{p.name}</span>
            <span style={{ width: 80, textAlign: 'right' }}>{p.price} 円</span>
            <span style={{ color: '#666' }}>{p.category}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
