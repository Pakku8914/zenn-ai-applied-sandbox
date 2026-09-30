import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from '../../../App';
import { products } from '../../../data/products';
import { reportWebVitals } from '../../../vitals';
// 予算違反の再現：押されたときにしか使わない関数を静的 import している。
// renderPrintCard は react-dom/server を使うので、サーバー描画用のライブラリごと初期 JS に入る
import { renderPrintCard } from '../../s05/print/renderPrintCard';

function PrintSample() {
  const [html, setHtml] = useState('');
  return (
    <section style={{ fontFamily: 'system-ui', padding: '0 24px', maxWidth: 960, margin: '0 auto' }}>
      <button id="print-button" type="button" onClick={() => setHtml(products.slice(0, 1).map(renderPrintCard).join(''))}>
        印刷用 HTML を作る
      </button>
      <pre id="print-output">{html}</pre>
    </section>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
    <PrintSample />
  </StrictMode>,
);

reportWebVitals();
