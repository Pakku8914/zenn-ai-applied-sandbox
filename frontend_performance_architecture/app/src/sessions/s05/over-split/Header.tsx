import { lazy, Suspense } from 'react';

const Title = lazy(() => import('./Title'));

export default function Header() {
  return (
    <header>
      <Suspense fallback={null}>
        <Title />
      </Suspense>
      <p>今週のおすすめ商品を集めました。</p>
    </header>
  );
}
