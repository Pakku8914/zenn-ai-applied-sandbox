import { StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../vitals';

/** S11 の各ページの入口。計測値は出発点と同じく window.__webVitals に貯める */
export function mount(node: ReactNode): void {
  const rootElement = document.getElementById('root');
  if (!rootElement) {
    throw new Error('#root が見つかりません');
  }
  createRoot(rootElement).render(<StrictMode>{node}</StrictMode>);
  reportWebVitals();
}
