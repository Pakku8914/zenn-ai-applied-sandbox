import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { PrintCatalog } from '../print/PrintCatalog';
// 静的 import：押されるかどうかに関係なく、react-dom/server ごと最初に読み込まれる
import { renderPrintCard } from '../print/renderPrintCard';
import { reportWebVitals } from '../../../vitals';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <PrintCatalog loadRenderer={() => Promise.resolve(renderPrintCard)} />
  </StrictMode>,
);

reportWebVitals();
