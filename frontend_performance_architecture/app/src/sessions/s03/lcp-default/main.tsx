import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { onLCP } from 'web-vitals';
import { App } from '../../../App';
import { reportWebVitals } from '../../../vitals';

declare global {
  interface Window {
    /** reportAllChanges を付けない既定の onLCP が報告した値（比較用） */
    __lcpDefault?: number;
  }
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// 本書の計測（reportAllChanges あり）はそのまま動かす
reportWebVitals();

// 比較用：既定の onLCP。LCP が「確定」するまで（最初の入力のあとアイドルになるか、
// タブが非表示になるまで）コールバックは呼ばれない
onLCP((metric) => {
  window.__lcpDefault = Math.round(metric.value * 1000) / 1000;
});
