import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../../vitals';
import { countRender } from '../renderCount';
import { PageIntro } from '../ResultList';
import { UrlCategoryFilter, UrlResults, UrlSearchBox } from '../UrlCatalogParts';
import { addToCart, cartStore, selectBookCount, selectCount } from './cartStore';
import { useStore } from './useStore';

function CartBadge() {
  countRender('CartBadge');
  const count = useStore(cartStore, selectCount);
  return <p id="cart-count">カート：{count} 点</p>;
}

function CartBookBadge() {
  countRender('CartBookBadge');
  // 書籍の数が変わったときだけ再レンダリングされる（雑貨を足しても 0 のまま）
  const books = useStore(cartStore, selectBookCount);
  return <p id="cart-books">うち書籍：{books} 点</p>;
}

// 絞り込みは URL、カートは外部ストア、一覧と件数は計算。ルートは状態を持たない
function StoreCatalog() {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（URL ＋ 外部ストア版）</h1>
      <PageIntro />
      <UrlSearchBox />
      <UrlCategoryFilter />
      <CartBadge />
      <CartBookBadge />
      <UrlResults onAdd={addToCart} />
    </main>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <StoreCatalog />
  </StrictMode>,
);
reportWebVitals();
