import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from '../../../App';
import { startLongFrameMonitor } from '../longFrameMonitor';
import { reportWebVitals } from '../../../vitals';

// 比較の基準：出発点の App をそのまま描き、長いタスクの記録だけを足したページ
const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

startLongFrameMonitor();
createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
reportWebVitals();
