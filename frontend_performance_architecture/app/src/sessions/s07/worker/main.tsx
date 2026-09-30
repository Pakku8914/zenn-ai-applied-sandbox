import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { CatalogShell } from '../CatalogShell';
import { WorkerChart } from './WorkerChart';
import { startLongFrameMonitor } from '../longFrameMonitor';
import { reportWebVitals } from '../../../vitals';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

startLongFrameMonitor();
createRoot(rootElement).render(
  <StrictMode>
    <CatalogShell Chart={WorkerChart} />
  </StrictMode>,
);
reportWebVitals();
