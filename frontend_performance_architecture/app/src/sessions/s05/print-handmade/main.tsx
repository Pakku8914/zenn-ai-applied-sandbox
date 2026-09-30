import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { PrintCatalog } from '../print/PrintCatalog';
// 依存を1つ減らした版：数十行の自作関数なので、分割せずに最初から持っていてよい
import { printCardHtml } from '../print/printCardHtml';
import { reportWebVitals } from '../../../vitals';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <PrintCatalog loadRenderer={() => Promise.resolve(printCardHtml)} />
  </StrictMode>,
);

reportWebVitals();
