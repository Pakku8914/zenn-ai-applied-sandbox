import { StrictMode, useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { products } from '../../../data/products';
import { reportWebVitals } from '../../../vitals';
import { createLab } from './lab-api';

/**
 * S06 の実験台。2,000 行の価格バー一覧と、右から出るカートパネルを置く。
 * 見た目は index.html の <style> で決め、ここでは DOM の骨組みだけを作る。
 */
function LabPage() {
  const listRef = useRef<HTMLUListElement>(null);
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (listRef.current && panelRef.current) {
      window.__s06Lab = createLab(listRef.current, panelRef.current);
    }
  }, []);

  return (
    <main className="lab">
      <h1>価格バーの一覧（S06 の実験台）</h1>
      <p className="controls">
        <button type="button" onClick={() => window.__s06Lab?.drawBars('thrashing')}>
          バーを描く（Bad）
        </button>
        <button type="button" onClick={() => window.__s06Lab?.drawBars('batched')}>
          バーを描く（Good）
        </button>
        <button type="button" onClick={() => void window.__s06Lab?.animate('transform', 1000)}>
          カートを開く
        </button>
      </p>
      <ul className="bars" ref={listRef}>
        {products.map((p) => (
          <li key={p.id} className="bar-row" data-price={p.price}>
            <span className="bar-name">{p.name}</span>
            <span className="bar-price">{p.price} 円</span>
            <span className="bar-track">
              <span className="bar" />
            </span>
            <span className="bar-stock">在庫 0</span>
          </li>
        ))}
      </ul>
      <aside className="cart-panel" ref={panelRef}>
        <h2>カート</h2>
        <p>商品はまだありません。</p>
      </aside>
    </main>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}
createRoot(rootElement).render(
  <StrictMode>
    <LabPage />
  </StrictMode>,
);
reportWebVitals();
