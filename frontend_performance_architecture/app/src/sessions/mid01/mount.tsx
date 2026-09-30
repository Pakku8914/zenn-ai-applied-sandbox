import { StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';

/**
 * 中間プロジェクトの各ページで共通の描画入口。
 * 見出しと導入文は HTML に直接書いてあり、React は #root の中（入力欄から下）だけを描く。
 */
export function mountMid01(node: ReactNode): void {
  const rootElement = document.getElementById('root');
  if (!rootElement) {
    throw new Error('#root が見つかりません');
  }
  createRoot(rootElement).render(<StrictMode>{node}</StrictMode>);
}
