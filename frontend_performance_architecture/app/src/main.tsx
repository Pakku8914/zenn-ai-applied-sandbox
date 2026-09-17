import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { reportWebVitals } from './vitals';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// 計測値を window に貯める。Playwright 側からこれを読み取って検証する
reportWebVitals();
