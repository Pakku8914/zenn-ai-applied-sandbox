import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { products } from '../../../data/products';
import { reportWebVitals } from '../../../vitals';
import { CatalogPage } from '../catalog/CatalogPage';
import { PageLayout } from '../ui/PageLayout';

// 通信で届く JSON を模す。文字列を経由するので、受け取る側には中身の型が分からない
const body = JSON.stringify(products);
function loadFromNetwork(): Promise<unknown> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(JSON.parse(body)), 300);
  });
}

// 責務で分けた版：レイアウト（再利用）→ 取得（CatalogPage）→ 状態（ProductCatalog）→ 表示（ProductListView）
const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <PageLayout title="商品カタログ（責務で分割した版）">
      {/* load はモジュールの最上位で作った関数なので、再レンダリングで作り直されない */}
      <CatalogPage load={loadFromNetwork} />
    </PageLayout>
  </StrictMode>,
);
reportWebVitals();
