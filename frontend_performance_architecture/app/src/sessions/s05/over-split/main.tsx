import { lazy, StrictMode, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { reportWebVitals } from '../../../vitals';

// 分割しすぎの Bad 例。「部品は全部 lazy にすれば軽くなる」と考えて、
// 最初の画面に必要な部品まで入れ子で遅延読み込みにしている。
// main → Layout → Header → Title と、1段ずつ取得しないと次の import() が始まらない。
const Layout = lazy(() => import('./Layout'));

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <Suspense fallback={null}>
      <Layout />
    </Suspense>
  </StrictMode>,
);

reportWebVitals();
