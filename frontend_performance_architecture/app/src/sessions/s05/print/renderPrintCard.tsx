import { renderToString } from 'react-dom/server';
import type { Product } from '../../../data/products';

function PrintCard({ product }: { product: Product }) {
  // 価格と単位は1つの文字列にする。別々の子にすると React が間に <!-- --> を挟む
  return (
    <article className="print-card">
      <h2>{product.name}</h2>
      <p>{`${product.price} 円`}</p>
      <p>{product.category}</p>
    </article>
  );
}

/**
 * 印刷用の商品カードを HTML 文字列にする（react-dom/server を使う版）。
 * 手軽だが、印刷のためだけにサーバー描画用の大きな依存をブラウザへ送ることになる。
 */
export function renderPrintCard(product: Product): string {
  return renderToString(<PrintCard product={product} />);
}
