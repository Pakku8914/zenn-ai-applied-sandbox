import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { PrintCatalog } from '../print/PrintCatalog';
import { reportWebVitals } from '../../../vitals';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

// 動的 import()：ボタンが押されたときに初めて、別チャンクとして取得される
const loadRenderer = () => import('../print/renderPrintCard').then((m) => m.renderPrintCard);

createRoot(rootElement).render(
  <StrictMode>
    <PrintCatalog loadRenderer={loadRenderer} />
  </StrictMode>,
);

reportWebVitals();
