import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../../vitals';
import { PageIntro } from '../ResultList';
import { CartBadge, CartBookBadge, CatalogProvider, CatalogResults, CategoryFilter, SearchBox } from './CatalogGood';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（Context を分割した Good 版）</h1>
      <CatalogProvider>
        <PageIntro />
        <SearchBox />
        <CategoryFilter />
        <CartBadge />
        <CartBookBadge />
        <CatalogResults />
      </CatalogProvider>
    </main>
  </StrictMode>,
);
reportWebVitals();
