import { Suspense } from 'react';
import { loadReviews, loadStock } from '../../lib/s12/practice';

export const metadata = { title: 'S12 練習問題4 境界を分けたストリーミング' };
export const dynamic = 'force-dynamic';

async function StockSection() {
  const stock = await loadStock(1); // 600ms
  return (
    <section id="stock">
      <h2>在庫</h2>
      <p>商品1 の在庫：{stock} 個</p>
    </section>
  );
}

async function ReviewSection() {
  const reviews = await loadReviews(); // 1,800ms
  return (
    <section id="reviews">
      <h2>レビュー</h2>
      <ul>
        {reviews.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </section>
  );
}

/** 速い部分と遅い部分を別々の Suspense で囲む。在庫はレビューを待たずに表示される */
export default function Page() {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品1 の詳細</h1>
      <p>価格：137 円・カテゴリ：書籍</p>
      <Suspense fallback={<p id="stock-fallback" style={{ minHeight: 80 }}>在庫を確認中です…</p>}>
        <StockSection />
      </Suspense>
      <Suspense fallback={<p id="reviews-fallback" style={{ minHeight: 120 }}>レビューを読み込み中です…</p>}>
        <ReviewSection />
      </Suspense>
    </main>
  );
}
