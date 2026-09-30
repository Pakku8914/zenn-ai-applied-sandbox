import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../../vitals';
import { PageIntro } from '../ResultList';
import { UrlCategoryFilter, UrlResults, UrlSearchBox } from '../UrlCatalogParts';

// 絞り込みの状態（キーワード・カテゴリ）を URL に置いた版。共有も戻る操作も URL が担う
function UrlStateCatalog() {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（URL に状態を置く版）</h1>
      <PageIntro />
      <UrlSearchBox />
      <UrlCategoryFilter />
      <UrlResults />
    </main>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <UrlStateCatalog />
  </StrictMode>,
);
reportWebVitals();
