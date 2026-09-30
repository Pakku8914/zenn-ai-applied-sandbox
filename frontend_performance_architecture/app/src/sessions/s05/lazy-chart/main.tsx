import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { LazyChartApp } from './LazyChartApp';
import { reportWebVitals } from '../../../vitals';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <LazyChartApp />
  </StrictMode>,
);

reportWebVitals();
