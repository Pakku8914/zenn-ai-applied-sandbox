import { lazy, Suspense } from 'react';

const Header = lazy(() => import('./Header'));
const ProductList = lazy(() =>
  import('../../../components/ProductList').then((m) => ({ default: m.ProductList })),
);

export default function Layout() {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <Suspense fallback={null}>
        <Header />
      </Suspense>
      <Suspense fallback={null}>
        <ProductList keyword="" />
      </Suspense>
    </main>
  );
}
