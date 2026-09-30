import { products } from '../../../../data/products';
import { CartSummary, useCart } from '../features/cart';
import { ProductCatalog } from '../features/catalog';

/** 組み立て役。feature 同士をつなぐ（catalog の「入れる」を cart の add に渡す）のはここだけ */
export function CatalogApp() {
  const cart = useCart();

  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ</h1>
      <CartSummary lines={cart.lines} />
      <ProductCatalog items={products} onAdd={cart.add} />
    </main>
  );
}
