import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { products, type Product } from '../../../data/products';
import { reportWebVitals } from '../../../vitals';
import { filterProducts } from '../catalogQuery';
import { countRender } from '../renderCount';
import { PageIntro, ResultList } from '../ResultList';
import { UrlCategoryFilter, UrlSearchBox } from '../UrlCatalogParts';
import { useCatalogSelector } from '../urlState';

/**
 * Bad：URL から計算できる絞り込み結果を、もう1つの state に写している。
 * 入力のたびに「古い結果で1回 → effect で state を直してもう1回」と2回描画する。
 */
function SyncedResults() {
  countRender('CatalogResults');
  const keyword = useCatalogSelector((q) => q.keyword);
  const category = useCatalogSelector((q) => q.category);
  const [items, setItems] = useState<Product[]>(() => filterProducts(products, { keyword, category }));

  useEffect(() => {
    setItems(filterProducts(products, { keyword, category }));
  }, [keyword, category]);

  return <ResultList items={items} />;
}

function DerivedBadCatalog() {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（派生状態を state に持つ Bad 版）</h1>
      <PageIntro />
      <UrlSearchBox />
      <UrlCategoryFilter />
      <SyncedResults />
    </main>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <DerivedBadCatalog />
  </StrictMode>,
);
reportWebVitals();
