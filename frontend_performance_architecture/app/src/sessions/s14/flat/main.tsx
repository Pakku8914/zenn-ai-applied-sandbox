import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../../vitals';
import { App } from './App';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
reportWebVitals();
