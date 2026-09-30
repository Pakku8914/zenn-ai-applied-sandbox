import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ProductList } from '../../components/ProductList';

/**
 * S04 の各ページで共通の商品一覧を #root に描画する。
 * 見出しとヒーロー画像は HTML に直接書いてあり、ここでは描画しない
 * （読み込みの指定だけを変えて比べるため、画面の中身は全ページで同じにしてある）。
 */
export function mountCatalog(): void {
  const rootElement = document.getElementById('root');
  if (!rootElement) {
    throw new Error('#root が見つかりません');
  }
  createRoot(rootElement).render(
    <StrictMode>
      <ProductList keyword="" />
    </StrictMode>,
  );
}
