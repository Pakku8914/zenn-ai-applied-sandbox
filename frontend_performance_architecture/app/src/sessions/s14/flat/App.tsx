import { useState } from 'react';
import { products } from '../../../data/products';
import { CartSummary } from './components/CartSummary';
import { ProductCatalog } from './components/ProductCatalog';
import type { CartLine } from './utils/cart';

/** 種類別（components/・utils/）に並べた版。画面は feature 構成の版と1文字も変わらない */
export function App() {
  const [lines, setLines] = useState<CartLine[]>([]);

  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ</h1>
      <CartSummary lines={lines} />
      <ProductCatalog items={products} lines={lines} setLines={setLines} />
    </main>
  );
}
