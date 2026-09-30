import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../../vitals';
import { SpaCatalog } from './SpaCatalog';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <SpaCatalog />
  </StrictMode>,
);

reportWebVitals();
