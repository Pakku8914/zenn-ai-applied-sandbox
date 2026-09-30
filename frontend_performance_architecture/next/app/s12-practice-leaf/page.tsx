import { products } from '../../lib/s12/products';
import { FavoriteButton } from './FavoriteButton';

export const metadata = { title: 'S12 練習問題5 境界を葉に寄せた版' };

/** カードの本体はサーバーで描く。押せるボタンだけがクライアントコンポーネント */
export default function Page() {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>お気に入り登録</h1>
      {products.slice(0, 20).map((p) => (
        <article
          key={p.id}
          data-card="s12-practice-card"
          style={{ borderBottom: '1px solid #ddd', padding: '8px 0' }}
        >
          <h2 style={{ fontSize: 16, margin: 0 }}>{p.name}</h2>
          <p style={{ margin: '4px 0' }}>
            {p.price} 円・{p.category}
          </p>
          {/* props は数値 1 つだけ。関数や Product 全体は渡さない */}
          <FavoriteButton productId={p.id} />
        </article>
      ))}
    </main>
  );
}
