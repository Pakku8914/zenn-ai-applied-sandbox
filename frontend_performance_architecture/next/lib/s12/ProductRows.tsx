import type { Product } from './products';

/**
 * 一覧の表示部品。'use client' を書いていないので、どちら側で動くかは「誰が import したか」で決まる。
 * - サーバーコンポーネントから import されれば、サーバーでだけ実行され、コードはブラウザに届かない
 * - 'use client' のファイルから import されれば、クライアントのバンドルに入る
 * data-component の文字列は、クライアントの JS に含まれたかどうかを検証で調べる目印。
 */
export function ProductRows({ products }: { products: readonly Product[] }) {
  return (
    <section data-component="s12-product-rows">
      <h2>商品一覧（{products.length} 件）</h2>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {products.map((p) => (
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
