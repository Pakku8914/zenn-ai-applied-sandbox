import { products } from '../../lib/s12/products';
import { ClientCatalog } from './ClientCatalog';

export const metadata = { title: 'S12 境界を根元に置いた版' };
// RSC 版と条件を揃えるため、こちらもリクエストごとに描画する
export const dynamic = 'force-dynamic';

export default function Page() {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（全部クライアント版）</h1>
      {/* 2,000 件の配列が props としてシリアライズされ、HTML に埋め込まれて届く */}
      <ClientCatalog products={products} />
    </main>
  );
}
