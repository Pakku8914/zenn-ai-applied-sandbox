import type { ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../vitals';
import { resetRenderCount } from './renderCount';

/**
 * S08 の各ページの入口。StrictMode は使わない。
 * StrictMode は開発時だけ本体を2回呼んで副作用の混入を見つける仕組みで、本番ビルドでは二重呼び出しは起きない。
 * 開発サーバーで数えても本番ビルドと同じ回数になるよう、このセッションのページでは外してある。
 */
export function mount(node: ReactNode): void {
  const rootElement = document.getElementById('root');
  if (!rootElement) {
    throw new Error('#root が見つかりません');
  }
  resetRenderCount();
  createRoot(rootElement).render(node);
  reportWebVitals();
}
