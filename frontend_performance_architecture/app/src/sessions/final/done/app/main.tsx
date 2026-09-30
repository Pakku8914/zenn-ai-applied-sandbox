import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../../../vitals';
import { CatalogApp } from './CatalogApp';

// feature 単位の構成の入口。app/ は組み立てだけを行う
const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <CatalogApp />
  </StrictMode>,
);

reportWebVitals();
